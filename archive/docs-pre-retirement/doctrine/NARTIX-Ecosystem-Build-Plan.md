# NARTIX ECOSYSTEM BUILD PLAN

**Version**: April 2026
**Updated with**: Full Framework for Claude Building Coding Prompts in VS Code through Copilot using Claude Opus 4.6

---

## CORE VISION

NARTIX is a vertically integrated AI factory.

- **Mobile layer**: iPhone with Natrix + Grok app (first strike, X, Grokipedia)
- **Orchestration layer**: Paperclip on Mac Mini
- **Architecture layer**: Jake Van Clief Model Workspace Protocol (MWP) folders
- **Execution layer**: Claude Desktop Max with Code, Computer Use, and Cowork — now with a complete framework where Claude builds and sends coding prompts directly into VS Code through GitHub Copilot Chatbot / Agent Mode running Claude Opus 4.6

Claude acts as permanent council chair and moderator on the Mac Mini. Heavy council debates, multi-LLM collaboration, simulation, and final review happen on the Mac Mini to leverage its CPU. iPhone stays lightweight for command and final notification only.

---

## FULL FLOW WITH HYBRID CODING PHASE

1. **iPhone**: Natrix + Grok does first strike and light council prep
2. Grok formats a rich pump prompt
3. iOS Shortcut sends pump to Mac Mini via Tailscale or bit-rage-labour.com Cloudflare Tunnel
4. Paperclip receives the pump and spawns a task-specific council
5. Claude chairs the council on Mac Mini using advanced multi-LLM collaboration strategies with Grok, Gemini, Perplexity, GPT and others
6. Council output goes into MWP folders and flows to 03-Execution
7. **Hybrid coding phase in 03-Execution**: Claude (Desktop Max) builds a precise, advanced coding prompt and sends it to GitHub Copilot in VS Code (Copilot Chatbot / Agent Mode running Claude Opus 4.6)
8. Copilot (powered by Claude Opus 4.6) generates and applies the code in `working-files/`
9. Claude Code (Desktop Max) reviews, debugs, and analyzes the output in a tight feedback loop
10. If issues found: Claude builds and sends a specific improvement prompt back to Copilot (Claude Opus 4.6)
11. Repeat until the code meets all requirements from the original pump prompt and council-output.md
12. If good: Claude solidifies the code, commits it, signs off as complete in `signed-off.md`, and notifies Natrix and NCL
13. Verification finalizes in 04-Review
14. Results and feedback sent back to iPhone Grok app

---

## FRAMEWORK FOR CLAUDE BUILDING CODING PROMPTS IN VS CODE THROUGH COPILOT (Claude Opus 4.6)

This is the exact operational framework Claude Desktop Max follows in 03-Execution/. It leverages Claude's Computer Use capability for automation where needed, but keeps the process simple and reliable.

### Step-by-step process

1. Claude reads `council-output.md` and `task-plan.md` from 03-Execution/
2. Claude builds a high-quality coding prompt using advanced techniques (Outcome + Constraints + Examples, Context Puck, Acceptance Criteria, etc.)
3. Claude writes the prompt as a large block comment at the top of a new or existing file in `working-files/` (or directly into Copilot Chat via Computer Use)
4. Claude triggers Copilot Chatbot / Agent Mode (running Claude Opus 4.6) by placing the cursor in the file and using a simple `@Copilot` mention or by sending the prompt to the Chat window
5. Copilot (Claude Opus 4.6) generates the code and applies it
6. Claude Code (Desktop Max) immediately reviews the result, runs local tests if applicable, and either approves or builds a precise fix prompt and repeats step 3
7. When satisfied, Claude commits the changes with a clear message and creates `signed-off.md`

### Practical implementation details

- **Computer Use mode**: Use Claude Desktop's Computer Use feature to automate the "send to Copilot" step for full hands-off operation (Claude can literally move the mouse, type into VS Code, and submit to Copilot Chat)
- **Manual-assisted mode**: Claude writes the prompt to `current-copilot-prompt.md` in 03-Execution/. You (or a simple VS Code task) copy-paste it into Copilot Chatbot
- **Persistent instructions**: Store in `.github/copilot-instructions.md` so Opus 4.6 always respects NARTIX style
- **Feedback loop limit**: Maximum 3 iterations to avoid token waste (Paperclip budget enforcement applies)

---

## ADVANCED MULTI-LLM COLLABORATION STRATEGIES

Claude enforces these in 02-Planning/:

1. **Hierarchical Delegation** — Claude delegates sub-problems to specialized sub-councils
2. **Debate Tournament with Elimination Rounds** — Models compete; Claude scores and eliminates
3. **Meta-Reasoning Loop** — Models critique their own and others' responses
4. **Simulated Annealing Collaboration** — Start creative, gradually converge
5. **Cross-Model Knowledge Distillation** — Generate, distill, re-expand
6. **Uncertainty-Aware Voting** — Include confidence scores and risks
7. **Escalation with Human-in-the-Loop Trigger** — Package open questions for Natrix

---

## ADVANCED COPILOT PROMPTING TECHNIQUES

### Technique 1: Outcome + Constraints + Examples

```
// Build a new Grok chat integration panel for the NARTIX IDE.
// Goal: Sidebar panel that streams responses from Grok API with real-time X context.
// Requirements: Use Monaco editor, support streaming with cancellation,
//   handle rate limits gracefully, follow existing dark theme.
// Example input: { prompt: "analyze trends", context: "X posts about AI" }
// Expected output: Clean React component with TypeScript, full error handling, unit test stub.
```

### Technique 2: Context Puck

```
// CONTEXT PUCK: Relevant files for this refactor
// From src/core/panel-system.ts: panels use React + dragula.
// Task: Refactor terminal integration for multiple concurrent sessions.
// Constraints: Keep backward compatibility, add session naming.
```

### Technique 3: Agent Mode Task with Acceptance Criteria

```
"Implement the verification protocol.
Acceptance criteria: Parse verification-report.json, run tests, compare against pump prompt,
output structured JSON only."
```

### Technique 4: Debugging Loop Prompt

```
"Previous implementation has null pointer on empty context.
Fix exactly that while preserving streaming logic.
Add comments explaining each change."
```

### Technique 5: Persistent House Rules

Create `.github/copilot-instructions.md` with project-wide style (TypeScript strict, JSDoc, error handling pattern).

---

## MWP NAVIGATION RULES

- **Layer 0**: COUNCIL.md (global rules)
- **Layer 1**: Per-folder CONTEXT.md (stage rules)
- **Layer 2**: Task files

Move outputs between folders as inputs for the next stage. File naming: `TYPE-STATUS-VERSION.md`.

---

## GLOBAL STANDARDS

- **Coding**: Clean, documented, testable
- **Verification**: Always in 04-Review/. Output JSON with fields: success, issues, diffs, logs, fixPlan
- **Feedback**: Prepare summary for iPhone pump-back
- **Security**: Sandbox Computer Use. Respect Paperclip budgets
- **Grokipedia**: Cross-reference from Grokipedia-Cache/ when relevant

---

## WORKFLOW FOR PUMP PROMPTS

1. `01-Input/` — read pump
2. `02-Planning/` — Claude chairs council using advanced multi-LLM collaboration strategies
3. `03-Execution/` — Claude builds prompt and sends to Copilot (Claude Opus 4.6) → generates code → Claude Code reviews and loops until good → signs off
4. `04-Review/` — verify plus auto-fix max 2 rounds
5. `05-Output/` — final artifacts plus feedback payload

Follow this structure exactly.

---

## iOS SHORTCUT "Pump to NARTIX" STRUCTURE

1. Get Latest Grok Conversation or Ask for Input → store as `UserPrompt`
2. Text action to format rich JSON pump prompt body
3. Optional — Connect to Tailscale
4. GET Contents of URL: `http://{tailscale-ip}:8787/pump` or `https://bit-rage-labour.com/pump` (POST, JSON body)
5. Wait for Response → Show Alert or Speak Text with feedback summary (including sign-off notification from Claude)

---

## NEXT STEPS CHECKLIST

- [ ] Update Claude Desktop Max and enable Computer Use and Cowork
- [ ] Install Tailscale on Mac Mini and iPhone
- [ ] Set up Cloudflare Tunnel on bit-rage-labour.com
- [ ] Clone and run Paperclip
- [ ] Create the NARTIX-Ecosystem folder and add the updated files
- [ ] Build the iOS Shortcut
- [ ] Configure VS Code Copilot Chatbot / Agent Mode to use Claude Opus 4.6
- [ ] Send first test pump from iPhone that triggers a coding task
- [ ] Test the full loop with the new Claude prompt-building framework in action
