---
name: setup
description: First-run setup for the coding coach, a short interview that records the system's profile and one Goal and downloads the search models. Use when the engineer types /{{id}}:setup.
disable-model-invocation: true
---

# Setup

Follow the coaching contract of the coach skill: show what you'll save and save only on a yes.

## Checklist

1. **Context.** `coach_get_context`. If a profile exists, show it and ask what to change instead of starting over. If it lists several `projects` and none is active, ask which system to set up, or whether this is a new one (`/{{id}}:project`). If the Project already exists because another coach made it (its profile, or Goals and Decisions carrying a `coach`), say what it already holds and ask only for what this coach needs and the profile lacks: never ask again for a fact it shows. When the app gave a work folder that is linked to nothing, `create` links it to the new Project.
2. **Interview,** one question at a time, short answers are fine. When the Engineer works in a repository the host can read, offer to draft the stack from it (README, manifests such as `package.json` or `pyproject.toml`): say what you read and let them correct it.
   - the system in one line (`system`). When no Project is active (`project` is null), or this is another system, call `coach_project` with action `create` and the system's name as soon as you have it, so everything after is saved to that Project;
   - the stack (`stack`): languages, frameworks, datastores, infrastructure;
   - scale today (`scale`) and the targets that matter (`slos`): latency, availability, cost;
   - what can't change (`constraints`), team size (`team_size`) and where the system is (`lifecycle`: design, build, operate or evolve);
   - optional, one question: a recurring Focus and Check-in for this system (each period agree one to three Commitments, then review them with evidence). It is off unless they say yes: if yes, save `loop: on`, `loop_every` (weekly, fortnightly or monthly) and `checkin_day`; if they say no ("leave the loop off"), save `loop: off` so the answer is kept and you don't ask again; if they skip it, save nothing;
   - optional: where the repo, dashboards and ADRs live (`workspace`, e.g. `{"repo": "github.com/acme/api", "adrs": "docs/adr"}`);
   - optional: what to call them, their role and how they like answers (`name`, `role`, `answer_style`; ask for these, never infer them from their account, email or anything the host shows, and save only what they type here), and the time zone `coach_get_context` reports (`timezone`). Skip any already in the profile (`shared_fields` marks those from the Common profile).
3. **Save the profile.** Show the values under the Project's name ("Save to Payments API: …"), get a yes, then one `coach_update_profile` call (`stated` carries the Engineer's own words for `name`, `role` and `answer_style`). For `name`, `role`, `timezone` and `answer_style`, also ask "Use these for all your Projects and coaches?"; on a yes save them in a second call with `scope: "common"`.
4. **One Goal.** Ask for the engineering outcome that matters most over the next 4-12 weeks, with a measure and a target date ("p99 checkout latency under 200 ms by 2026-12-15"). Confirm, then `coach_record` kind `goal`.
5. **Models.** The search models (about 0.2 GB, once) download by themselves in the background; search uses keyword matches until they finish. Say that in one sentence; `coach_corpus_status` shows `search_mode`.
6. **Close** with what's saved, the Project it's in, where it lives (the `FOUNDER.md` path `coach_corpus_status` reports, readable any time) and three things to try: `/{{id}}:ask`, `/{{id}}:design-review`, `/{{id}}:decision-record`.

## Gotchas

- If `uvx` is missing, the coach can't start: tell them to install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Everything stays on this machine. Say so once, in the Close, together with the local usage log of which tools ran and how long they took (never their words), kept 90 days; `{{env_prefix}}USAGE=0` turns it off.
- Reading the repo is for the profile only: never save code, secrets or file contents to memory.
