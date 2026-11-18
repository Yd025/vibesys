# FPGA HLS Evaluator Design

The evaluator grades a candidate FPGA accelerator written in high-level
synthesis (HLS) C++ for tasks in the `fpga-hls` domain. It answers three
questions in order: is the design correct, does it fit the target device at
the target clock, and how fast is it. When a design does not fit, it names the
binding limit with the report numbers that show it.

AMD Vitis does the hardware work. It is slow (synthesis takes minutes and
implementation can take far longer), it needs a licensed install, and CI does
not have it. The design therefore keeps every decision in code that runs
without Vitis, and confines Vitis to one narrow shell that the tests replace
with recorded reports.

## Terms

- **Stage**: one Vitis flow step. In order: C simulation (runs the C++ against
  the testbench), C synthesis (produces RTL and estimates of latency and
  resources), co-simulation (runs the generated RTL against the same
  testbench and measures cycles), and implementation (places and routes the
  design on the device and reports real resource use and timing).
- **Device**: the target FPGA part, for example `xc7a35tcpg236-1` (the Artix-7
  on a Digilent Basys 3 board). Its capacity per resource class (LUT,
  flip-flop, DSP, block RAM, UltraRAM) lives in the evaluator's device table.
- **Slack**: how much time is left in the clock period on the slowest path.
  Negative worst slack means the design does not close timing at the target
  clock.
- **Binding limit**: the resource class or the timing constraint that a design
  exceeds, or the one closest to its limit.
- **Verdict**: the evaluator's result for one candidate: failed correctness,
  infeasible with a binding limit, or feasible with measured performance.

## Who owns what

The task owns the reference, the testbench, the accuracy checker, the device
part, the clock period and the problem shape. It passes the part and clock to
the evaluator as entrypoint arguments. The evaluator writes the Vitis script
itself. The candidate supplies only kernel source files. Nothing the
candidate edits can change the part, the clock, the testbench or the tool
configuration; the example registry's trust-policy check keeps the files the
commands read out of the candidate's writable set.

The `[accuracy]` entrypoint runs C simulation, and co-simulation where the
task requires it. The `[benchmark]` entrypoint runs the correctness gate
first, then synthesis and implementation, and writes the verdict and metrics
as JSON.

## Structure: pure core, thin shell

The core is pure functions over typed values:

- **Report parsing**: raw report files to typed numbers (latency in cycles,
  initiation interval, estimated and achieved clock, worst slack, use of each
  resource class). A missing or malformed field is an error that names the
  file and the field, never a silent zero.
- **Verdict**: typed reports plus a device to a verdict. Post-implementation
  numbers replace synthesis estimates whenever both exist.
- **Stage machine**: the current stage and its result to the next stage or a
  stop. Every stop records its reason, such as "stopped after C synthesis: DSP
  112 of 90".

The shell is the only code that knows Vitis commands, paths and environment
variables. It sits behind one interface, `HlsToolchain`, with one method per
stage. Each method takes the kernel sources, the part and the clock, and
returns the stage's exit status, its log and its raw report directory.

`HlsToolchain` has two implementations:

- `VitisHlsToolchain` runs the real tools as subprocesses with a configurable
  timeout per stage.
- `RecordedHlsToolchain` replays report directories captured from real runs.
  It also injects faults: a crash, a timeout, a license failure, or a report
  directory that is partial or missing.

Both pass the same contract suite. The real implementation runs that suite
only on a host with Vitis installed.

## Failure classification

A failed stage maps to the existing `EvidenceFailureKind`:

- **Workload**: the candidate failed: wrong outputs, a synthesis error caused
  by its code, a resource class over capacity, or negative slack. This is a
  permanent fact about that candidate.
- **Infrastructure**: the machinery failed: a license error, a missing tool,
  a crash of the tool itself, or a stage timeout. This says nothing about the
  candidate and must never become an infeasibility verdict.
- **Ambiguous**: the evaluator cannot tell which one occurred.

Getting this wrong in the infrastructure-to-workload direction is the worst
error the evaluator can make, because it would turn a tool problem into a
false hardware limit.

## Correctness properties

| Property | Cheapest check |
| --- | --- |
| The candidate cannot change the part, clock, testbench, reference or tool script. | By construction: they come from task arguments and the evaluator's own script, and the trust-policy check covers the files. |
| A verdict is feasible exactly when every resource class is at or under capacity and worst slack is at least zero. | Property test over generated report numbers and every device in the table. |
| An infeasible verdict names a limit that the report numbers exceed. | The same property test. |
| Implementation numbers override synthesis estimates when both exist. | Unit test on recorded report pairs. |
| Tool, license and timeout failures are infrastructure, never workload. | Fault injection through `RecordedHlsToolchain`. |
| No later stage runs after an earlier stage fails, and every stop records its reason. | Stage-machine tests with `RecordedHlsToolchain`. |
| Known-wrong kernels fail correctness. | Off-by-one, too-narrow accumulator and skipped-row kernels must fail C simulation. |
| Latency cannot be changed by pragmas alone. | Co-simulation cycles are compared with the synthesis estimate; a mismatch beyond the tolerance is flagged, which catches trip-count hints that disagree with real loop bounds. |
| Malformed reports fail loudly. | Parser tests on truncated reports and reports with missing fields. |

## Verification ladder

Each level runs only after the one below it passes.

1. **Static.** Typed `Device`, `Stage` and `Verdict` values. The device table
   refuses a part it does not list.
2. **Unit and property tests.** Parser, verdict and stage machine against
   recorded reports. These are deterministic and run in CI in seconds.
3. **Fault injection.** Crashes, timeouts, license errors and partial report
   directories through `RecordedHlsToolchain`.
4. **Real tier, on a host with Vitis.** Four designs whose outcomes are known
   in advance:
   - a 64-element vector add, which fits;
   - a baseline tutorial matmul, which fits;
   - a matmul unrolled past the device's 90 DSPs, which is infeasible with DSP
     binding;
   - a design constrained to a clock it cannot meet, which is infeasible with
     timing binding.

   Their report directories become the fixtures for level 2, which also
   checks that the recorded replay matches the real tools.
5. **Live.** One small VibeSys run on the tutorial matmul task, run only when
   level 4 passes, so a broken evaluator never costs a full agent run.

These levels map onto the repository's test tiers: levels 1 to 3 are
deterministic-tier tests, and level 4 belongs with the real tiers.

## Current limits

- Only parts listed in the device table can be targeted; the first entry is
  `xc7a35tcpg236-1`.
- Measurements come from reports and co-simulation, not from a programmed
  board.
- A run-level infeasibility verdict is not modeled: a design that does not
  fit is a workload failure of that candidate.
