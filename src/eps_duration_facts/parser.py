"""Narrow replay of observed MOPS Inline XBRL; not a general taxonomy engine."""
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

from lxml import etree, html

from .model import Fact, FiscalCalendar, Rejected, require
from .raw import verify_receipt

NS = {"ix": "http://www.xbrl.org/2013/inlineXBRL",
      "i": "http://www.xbrl.org/2003/instance"}
TAXONOMIES = ("http://xbrl.ifrs.org/taxonomy/2017-03-09/ifrs-full",
              "https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full")
TRANSFORM = "http://www.xbrl.org/inlineXBRL/transformation/2015-02-26"


def text(node):
    return "".join(node.itertext()).strip()


def qname(node, value):
    parts = value.split(":")
    require(len(parts) == 2 and parts[0] in node.nsmap, "QNAME_UNPROVEN")
    return "{" + node.nsmap[parts[0]] + "}" + parts[1]


def duration(start, end, calendar_evidence):
    if not calendar_evidence:
        return "UNPROVEN"
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin.year != finish.year or finish.month not in (3, 6, 9, 12):
        return "UNPROVEN"
    if finish.day != calendar.monthrange(finish.year, finish.month)[1]:
        return "UNPROVEN"
    if begin == date(begin.year, 1, 1) and finish.month == 12:
        return "ANNUAL"
    if begin == date(begin.year, finish.month - 2, 1):
        return "QUARTER"
    if begin == date(begin.year, 1, 1):
        return "YEAR_TO_DATE"
    return "UNPROVEN"


def parse_book_calendar(receipt, data, symbol):
    endpoint = receipt["endpoint"]
    url = urlsplit(endpoint)
    require(url.netloc == "doc.twse.com.tw" and url.path == "/server-java/t57sb01"
            and parse_qs(url.query).get("co_id") == [symbol], "CALENDAR_SOURCE_INVALID")
    attempt = verify_receipt(receipt, data, endpoint)
    root = html.fromstring(data)
    for node in root.xpath("//script | //style"):
        node.drop_tree()
    import re
    require(re.search(r"會計期間[：:]\s*曆年制", root.text_content()) is not None,
            "FISCAL_CALENDAR_UNPROVEN")
    return FiscalCalendar(symbol, 1, attempt["body_sha256"], receipt["label"],
                          "visible company accounting-period header: calendar-year")


def normalized(node):
    if node.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
        return None
    fmt = qname(node, node.get("format", ""))
    require(fmt == "{" + TRANSFORM + "}numdotdecimal", "TRANSFORMATION_UNSUPPORTED")
    raw = text(node)
    # This narrow observed transformation accepts a decimal, not arbitrary separators.
    import re
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw) is not None, "NUMERIC_FORMAT_INVALID")
    try:
        scale = int(node.get("scale", "0"))
        require(-12 <= scale <= 12, "SCALE_UNSUPPORTED")
        sign = node.get("sign")
        require(sign in (None, "-"), "SIGN_INVALID")
        result = Decimal(raw) * (Decimal(10) ** scale)
        return format(-result if sign == "-" else result, "f")
    except (InvalidOperation, ValueError) as exc:
        raise Rejected("NUMERIC_INVALID") from exc


def parse_inline(receipt, data, symbol, market, fiscal_calendar_evidence=None):
    if fiscal_calendar_evidence is not None:
        require(isinstance(fiscal_calendar_evidence, FiscalCalendar)
                and fiscal_calendar_evidence.symbol == symbol and fiscal_calendar_evidence.start_month == 1
                and fiscal_calendar_evidence.body_sha256 and fiscal_calendar_evidence.locator,
                "FISCAL_CALENDAR_BINDING_INVALID")
    endpoint = receipt["endpoint"]
    url = urlsplit(endpoint)
    args = parse_qs(url.query)
    require(url.netloc == "mopsov.twse.com.tw" and url.path == "/server-java/FileDownLoad"
            and args.get("functionName") == ["t164sb01"] and args.get("step") == ["9"]
            and args.get("co_id") == [symbol] and args.get("report_id") == ["C"],
            "SOURCE_BINDING_INVALID")
    attempt = verify_receipt(receipt, data, endpoint)
    try:
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                     load_dtd=False, recover=False))
    except etree.XMLSyntaxError as exc:
        raise Rejected("DOCUMENT_INVALID") from exc
    tree = root.getroottree()
    require(not tree.docinfo.doctype, "DTD_UNSUPPORTED")
    meta = {}
    for node in root.xpath("//ix:nonNumeric", namespaces=NS):
        local = node.get("name", "").split(":")[-1]
        if local in ("CompanyID", "Year", "Quarter", "Market", "ReportCategory"):
            expanded = qname(node, node.get("name"))
            require(expanded in tuple("{http://www.xbrl.org/tifrs/notes/" + version + "}" + local
                                     for version in ("2020-06-30", "2025-06-30", "2026-03-31")),
                    "IDENTITY_CONCEPT_UNPROVEN")
            require(local not in meta, "IDENTITY_DUPLICATE")
            meta[local] = text(node)
    require(meta.get("CompanyID") == symbol, "WRONG_ISSUER")
    require(meta.get("Market") == {"TWSE": "Listed company", "TPEX": "Over-the-counter"}.get(market),
            "WRONG_MARKET")
    require(args.get("year") == [meta.get("Year")] and args.get("season") == [meta.get("Quarter")],
            "RETURNED_PERIOD_MISMATCH")
    contexts, units = {}, {}
    for node in root.xpath("//i:context", namespaces=NS):
        key = node.get("id")
        require(key and key not in contexts, "CONTEXT_DUPLICATE")
        contexts[key] = node
    for node in root.xpath("//i:unit", namespaces=NS):
        key = node.get("id")
        require(key and key not in units, "UNIT_DUPLICATE")
        units[key] = node
    facts = []
    for node in root.xpath("//ix:nonFraction", namespaces=NS):
        local = node.get("name", "").split(":")[-1]
        if local not in ("BasicEarningsLossPerShare", "DilutedEarningsLossPerShare"):
            continue
        context = contexts.get(node.get("contextRef"))
        unit = units.get(node.get("unitRef"))
        require(context is not None and unit is not None, "CONTEXT_OR_UNIT_MISSING")
        def single(path):
            values = context.xpath(path, namespaces=NS)
            require(len(values) == 1, "CONTEXT_DURATION_UNPROVEN")
            return text(values[0])
        issuer = single("./i:entity/i:identifier")
        require(issuer == symbol, "WRONG_ISSUER")
        start, end = single("./i:period/i:startDate"), single("./i:period/i:endDate")
        require(date.fromisoformat(start) <= date.fromisoformat(end), "PERIOD_INVALID")
        scope = "CONSOLIDATED" if meta.get("ReportCategory") == "Consolidated report" else "UNPROVEN"
        if context.xpath("./i:entity/i:segment | ./i:scenario", namespaces=NS):
            scope = "UNPROVEN"
        numerator = unit.xpath("./i:divide/i:unitNumerator/i:measure", namespaces=NS)
        denominator = unit.xpath("./i:divide/i:unitDenominator/i:measure", namespaces=NS)
        unit_name = "UNPROVEN"
        if len(numerator) == len(denominator) == 1:
            if qname(numerator[0], text(numerator[0])) == "{http://www.xbrl.org/2003/iso4217}TWD" and \
                    qname(denominator[0], text(denominator[0])) == "{http://www.xbrl.org/2003/instance}shares":
                unit_name = "TWD/shares"
        concept = qname(node, node.get("name"))
        recognized = any(concept == "{" + namespace + "}" + local for namespace in TAXONOMIES)
        value = normalized(node)
        import re
        require(node.get("decimals") is None or re.fullmatch(r"-?\d+|INF", node.get("decimals")),
                "DECIMALS_INVALID")
        require(node.get("precision") is None or re.fullmatch(r"[1-9]\d*|INF", node.get("precision")),
                "PRECISION_INVALID")
        require(not (node.get("decimals") and node.get("precision")), "ACCURACY_ATTRIBUTES_CONFLICT")
        basis = ("BASIC" if local.startswith("Basic") else "DILUTED") if recognized else "UNPROVEN"
        period_kind = duration(start, end, fiscal_calendar_evidence)
        status = "PASS" if recognized and value is not None and scope != "UNPROVEN" and \
            unit_name != "UNPROVEN" and period_kind != "UNPROVEN" else "UNPROVEN"
        facts.append(Fact(symbol, market, issuer, concept, basis, scope, start, end, period_kind,
                          text(node), value, unit_name, node.get("scale"), node.get("decimals"),
                          node.get("precision"), None,
                          attempt["body_sha256"], None, "MOPS_INLINE_XBRL",
                          attempt["body_sha256"], receipt["label"], node.get("contextRef"),
                          tree.getpath(node), attempt["retrieved_at"], fact_semantics_status=status,
                          issuer_period_group=symbol + "-" + meta["Year"] + "Q" + meta["Quarter"]))
    require(facts, "EPS_FACTS_MISSING")
    return facts
