---
description: Structured workflow planning for complex tasks
argument-hint: [task description]
---

Execute the following structured planning workflow:

## 1. 📋 WHAT I UNDERSTAND
Provide a detailed breakdown of the task with:
- Numbered steps for sequential processes
- Clear objectives and expected outcomes
- Technical context and dependencies

## 2. ❓ CLARIFICATION QUESTIONS
Ask numbered questions (maximum 7) to clarify:
- Ambiguous requirements
- Technical approach preferences
- Edge cases and constraints
- Priority and scope

**Format:** Each question numbered, each option lettered on separate lines:
```
1. Question text?
   A. Option one
   B. Option two
   C. Option three
```

## 3. ✅ FINAL CONFIRMATION
Once clarifications are addressed:
- Summary of final understanding
- Numbered action plan with specific steps
- **WAIT FOR EXPLICIT APPROVAL** before executing

## AUTO-ACTIVATION TRIGGERS
Activate `/plan` automatically when detecting:
- Multi-step tasks or processes
- New feature implementation
- Complex requirements
- Ambiguous specifications
- "How should I proceed?" type questions

## DON'T ACTIVATE FOR
- Direct commands with clear intent
- Standard git operations
- Well-documented workflows (e.g., `/fresh`)
- Repetitive/routine tasks
- "Following protocol" commands

## TRUST RULE
**Direct instruction for known process = EXECUTE IMMEDIATELY**

Don't ask "should I...?" for documented procedures. Execute and report results.

## 💡 FOR NEXT TIME
After completing the plan, include optimization suggestions:
- Workflow improvements discovered
- Process optimizations identified
- Better approaches for similar tasks
- Documentation gaps to fill
