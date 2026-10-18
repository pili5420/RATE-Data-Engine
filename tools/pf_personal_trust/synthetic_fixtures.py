"""Fictional test fixtures only. Not Owner Consent, a Permit or original-host observations."""
import base64,copy,hashlib
import personal_model as m
TOOL='a'*64
NOW='2030-01-01T12:01:00Z'
def ctx():
    return {'host':'SYNTHETIC-PERSONAL-PC','sid':'S-1-5-21-100-200-300-1001','session':1,
            'boot_utc':'2030-01-01T00:00:00Z','volume_id':'\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\',
            'volume_serial':12345,'os_version':'10.0.0','os_build':'00000'}
def approval():
    return {'version':'PF_PERSONAL_SYNTHETIC_CONSENT_V1','realm':m.REALM,'tier':m.PERSONAL,
      'host_context':ctx(),'tool_sha256':TOOL,'scope_sha256':m.digest(m.SCOPE),'target':m.TARGET,
      'attempt':'SYNTHETIC-attempt-1','nonce':'b'*64,'approved':True,'owner_owns_manages':True,
      'owner_confirmation':'EXPLICIT_THIS_ATTEMPT_ONLY','not_before':'2030-01-01T12:00:00Z',
      'expires':'2030-01-01T12:05:00Z','evidence_destination':'D:\\RATE-Personal-Evidence\\SYNTHETIC-attempt-1',
      'accepted_risks':list(m.RISKS),'operation':'LOCAL_READ_ONLY_ONCE'}
def set_rows(e,index,rows):
    b=m.canonical(rows)+b'\n';r=e['records'][index]
    r.update(raw_base64=base64.b64encode(b).decode(),raw_sha256=hashlib.sha256(b).hexdigest())
def rows(e,index):
    import json
    return json.loads(base64.b64decode(e['records'][index]['raw_base64']))
def evidence():
    c=ctx()
    data={'account':[{'UserSID':c['sid'],'SessionId':c['session']}],
          'os':[{'CSName':c['host'],'Version':c['os_version'],'BuildNumber':c['os_build'],'LastBootUpTime':c['boot_utc']}],
          'computer':[{'Name':c['host'],'AutomaticManagedPagefile':False}],
          'volume':[{'DeviceID':c['volume_id'],'DriveLetter':'D:','SerialNumber':c['volume_serial']}],
          'tpm':[{'IsEnabled_InitialValue':True,'IsActivated_InitialValue':True,'IsOwned_InitialValue':True}],
          'settings':[{'Name':m.TARGET,'InitialSize':512,'MaximumSize':2048}],
          'usage':[{'Name':m.TARGET,'AllocatedBaseSize':512,'CurrentUsage':1,'PeakUsage':2,'TempPageFile':False}],
          'registry':[{'PagingFiles':['D:\\pagefile.sys 512 2048']}]}
    e={'version':'PF_PERSONAL_SYNTHETIC_EVIDENCE_V1','realm':m.REALM,'consent':approval(),'tool_sha256':TOOL,
       'scope':copy.deepcopy(m.SCOPE),'context_before':ctx(),'context_after':ctx(),
       'started_utc':'2030-01-01T12:00:01Z','ended_utc':'2030-01-01T12:00:50Z',
       'clock_source':'WINDOWS_LOCAL_UNTRUSTED','records':[]}
    for i,name in enumerate(m.ORDER):
        q=m._qid(name)
        e['records'].append({'sequence':i+1,'id':name,'query':copy.deepcopy(m.QUERIES[q]),'status':'OBSERVED',
            'started_utc':f'2030-01-01T12:00:{i*3+1:02d}Z','ended_utc':f'2030-01-01T12:00:{i*3+2:02d}Z',
            'raw_base64':None,'raw_sha256':None})
        set_rows(e,i,data[q])
    return e
def wire(e):return m.canonical(e)+b'\n'
def assess(e):return m.assess(wire(e),ctx(),TOOL,NOW)
def journal():return {'realm':m.REALM,'attempt':'SYNTHETIC-attempt-1','nonce':'b'*64,'events':[]}
