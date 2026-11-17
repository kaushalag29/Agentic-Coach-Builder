---
name: vault
description: Rebuilds the Project's vault now, a read-only folder of plain Markdown (one file per Note, Decision, Goal, Commitment, person and blocker, linked) that Obsidian or another graph viewer can open, plus a board per Goal and one graph page for a browser. Use when the person types /{{id}}:vault.
disable-model-invocation: true
---

# Vault

Every coach of the {{project_noun}} rebuilds the whole vault after each save, so it is normally current already. This rebuilds it now: to repair a folder that drifted, after a Nudge says a build failed, or to check it is up to date. It runs in the coach's own server, where the {{project_noun}}'s records are, so it works in every app, hosted sessions included: no shell is needed.

1. **Which {{project_noun}}.** The one this conversation chose (`coach_get_context` names it in `project`). If none has been chosen yet, ask which one first, as for any save, and don't guess.
2. **Build:** call `coach_project` with `action` `"vault"`. It reads every record in one consistent snapshot and writes only the {{project_noun}}'s own `vault/` folder. If it says another coach is building right now, that build runs once more for this request: say so.
3. **Report** the folder (`vault.path`) and how many files it wrote and removed. Tell the {{person}} to open that folder itself (not a folder inside it) as a vault in Obsidian (File → Open folder as vault) and open the graph view; Foam, Quartz and Logseq read the same files. Each Goal also has a board in `_meta/<folder>/canvas/` (Obsidian opens `.canvas` files), and `_meta/graph.html` opens in any browser, offline, with no Obsidian: search, filter by kind or week, click two records to see how they connect.
4. **Say what it is**: a read-only view. Edits to these files are overwritten at the next save; to change a record, change it through the coach. Files the {{person}} made in the folder (their own canvases, `.obsidian/`) are never touched. Records a coach keeps to itself (the investor's) are in that coach's own folder, never in `shared/`.
5. Don't open or summarise the files unless asked; they hold the {{person}}'s private notes and decisions.

## Gotchas

- If the build fails, say what the error says and stop: the records are unchanged, and the next save tries again. Don't copy or move the database, and don't run a shell command, to make it work.
- To write the vault to another folder, the {{person}} runs `{{id}} vault build --out <folder>` in a terminal; the tool writes only the {{project_noun}}'s own folder.
- Building files is not one coach reading another's memory: nothing from the vault enters this conversation.
