# Desktop Agent

Desktop Agent is a small, independent foundation for turning human desktop GUI test cases into inspectable saved tests. It separates reusable desktop interaction from testcase-specific interpretation and reporting.

It is intentionally conservative. A click request is recorded as an attempted action, not as proof that the expected result happened. Text delivery is separate from text correctness. Screenshots are evidence, not assertions by themselves. Each human step keeps its original action and expected result in the saved artifact and in the execution report.

## What Is Implemented

- A dependency-light Win32 desktop backend for visible window inspection, child control discovery, screenshots, mouse clicks, literal text entry, launch, and close requests.
- A deterministic memory backend for checking coordinator behavior without touching the desktop.
- A JSON saved-test artifact format that preserves the original testcase, interaction policy, demonstrated operations, expected results, cleanup, and assumptions.
- A replay runner that records intended actions, attempted actions, delivered input, observed consequences, evidence, assertions, failures, skipped dependent steps, and cleanup outcomes.
- A CLI for scaffolding a testcase, inspecting the desktop, and replaying saved artifacts.
- A controlled Tk GUI fixture and saved test demonstrating real GUI launch, observation, input, button activation, fresh output verification, and cleanup.
- Unit checks for ambiguity, policy denial, dependency skipping, stale/missing outputs, cleanup ownership, and target evidence.

## Environmental Assumptions

- The desktop session is already available and unlocked.
- Target applications are already installed.
- The test owns only resources it launches or explicitly observes as belonging to the run.
- The bundled Python runtime is available at the path used in `examples/fixture_test.json`; adjust that command if your runtime path differs.
- The Win32 backend is modest by design. It does not provide full Microsoft UI Automation patterns, OCR, or semantic accessibility trees. Unsupported requirements should remain incomplete or failed rather than hidden behind convenient bypasses.

## Basic Commands

Use the bundled Python executable in this workspace:

```powershell
& 'C:\Users\testuser\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m desktop_agent.cli inspect
```

Create a scaffold from a human testcase:

```powershell
& 'C:\Users\testuser\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m desktop_agent.cli scaffold examples\fixture_spec.json runs\fixture_scaffold.json
```

Run the demonstrated saved test:

```powershell
& 'C:\Users\testuser\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m desktop_agent.cli run examples\fixture_test.json --report runs\fixture_report.json
```

Run isolated checks:

```powershell
& 'C:\Users\testuser\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

## Authoring Workflow

1. Write or import a testcase as JSON. Each step has an `id`, original `action`, original `expected`, optional data, and constraints.
2. Run `scaffold` to create an artifact that preserves the testcase and policy.
3. Inspect the desktop and explore the target application through permitted GUI interactions. Record demonstrated operations in the artifact. Keep failed exploration attempts in separate run records when they matter.
4. Convert only demonstrated routes into replay operations. Do not add guessed shortcuts or direct state manipulation because they sound plausible.
5. Run the complete saved artifact. A pass requires every required step to pass its expected-result checks and cleanup verification.
6. If replay fails, inspect the report, repair the saved artifact, and run the whole artifact again.

## Interaction Policy

The policy lives in the testcase artifact. It controls whether relative coordinates, shortcuts, clipboard use, and read-only file verification are permitted. The runner refuses operations that violate the policy. A fallback must be represented explicitly with its reason and must still preserve the human step's meaning.

Visible control clicks use observed child windows by exact text and fail on ambiguity. Relative clicks are allowed only when the policy allows them and are anchored to an observed current window rectangle.

## Evidence And Reports

Reports are JSON. They include:

- The original step action and expected result.
- The route attempted for that step.
- Evidence objects such as observed windows, controls, files, file content checks, or screenshots.
- Delivered input, separated from verified requirements.
- Failures, skipped dependent steps, and cleanup results.

This is deliberately not a transcript of a model's private reasoning. It records observable choices, evidence, and conclusions.

## Example Lifecycle

`examples/fixture_spec.json` describes three human steps: open a fixture GUI, enter a message, and press `Create Output`. `examples/fixture_test.json` is the generated saved test. It removes stale fixture output before execution, launches the fixture, waits for the window, clicks the message field using an allowed observed-window-relative coordinate, types literal text, activates the button using an explicit window-relative route because Tk does not expose its caption through this small Win32 backend, waits for a fresh output file, reads the actual application-created file, and verifies the content. Cleanup closes the owned fixture window and removes the temporary output so a later run cannot pass on stale state.

## Limitations

- The current real backend is Windows-oriented and intentionally small.
- Complex custom-rendered applications may need an OCR, accessibility, or image-matching backend added behind the same interface.
- The system does not call an LLM by itself. It gives an AI or managed authoring workflow stable artifacts, operations, policies, and reports to use without making one conversation style part of correctness.
- The fixture demonstrates a narrow real GUI path. It is evidence for that path, not a blanket claim that every desktop application is supported.

## AGATA thesis materials

The GPT-5.5-generated comparison toolkit used in the AGATA thesis, published without manual code changes. The author defined the development task and organized the experiments; GPT-6.1 Sol xhigh produced its development instruction.

The `tdk-2026-10-24` tag preserves the first submission snapshot;
`tdk-2026-10-25` records the supplemented documentation and MIT licensing.
See [LICENSE](LICENSE). The original experiment-time code state cannot always be reconstructed from these later snapshots.
