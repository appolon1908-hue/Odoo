# CC-08 — AI Agent Assistant

This branch adds a bounded advisory record for interaction summaries, knowledge suggestions, and response drafts. It integrates with the existing AI modules while separating request, generation, and human-review authority.

## Enforced limits

- only hashes and controlled evidence references are retained for inputs;
- generation requires the AI service role or platform administrator;
- output length and SHA-256 evidence are validated;
- the requester cannot approve the same draft;
- approval records reviewer and timestamp but performs no send or business mutation;
- there is no model field or method for consent, DNC, refund approval, disposition finalization, provider delivery, or customer updates.
