# G01 R5 offline semantic classification

`r5_oracle.py` reads the R4 exact-source Oracle and the original 156 workflow
blob copies. It verifies the controlling Git tree, all 1,055 tracked path blob
IDs and the original 156 workflow bytes through an isolated readback repository.
It parses YAML but never executes workflow commands.

L1 describes syntax and literal values only. A fixed runner, shell command or
action reference may be syntactically readable without any assertion about
its runtime effects. A simple `github.ref` equality can be evaluated only
when the caller supplies a push branch; pull request refs stay unknown.
L2 always retains unqualified runtime effects. L3 always retains candidate
Check contexts and unknown Owner authority. Neither layer is promoted by
L1 parsing.

Example, with source and output paths outside the tracked repository:

```text
python -B tools/g01/r5_oracle.py --r4-oracle <R4>/generated/classification_oracle.json --source-workflows <R4>/generated/source_workflows --readback-repo <isolated-readback.git> --output <R5-output>
python -B -m unittest discover -s tools/g01 -p test_r5_oracle.py -v
```

The generated 156-row matrix is pinned to commit
`0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7` and tree
`dbeeb2cc67b43d4d9600b1f7eacee8ba8bdec820`. A PR containing this
tool does not change the controlling 1,055-path source inventory; a future
source update requires a separately authorized new baseline.
