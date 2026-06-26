# pick_my_task.md — Group WhatsApp (G21)

**Task board:** https://docs.google.com/spreadsheets/d/1YQ9-zaiOUhf6KXs-9ow3LNgFSXYPQYCrQQbWAksIc2Q/edit?usp=sharing
**Full task details:** [`HANDOFF.md`](https://github.com/rraghu214/glc_v1_whatsapp/tree/integration/glc/channels/catalogue/whatsapp/help_docs/HANDOFF.md) — search for the task ID (e.g. `US-6`)

## How to pick a task

1. On the sheet, find a row with **Status = Not Started**.
2. Check **Predecessor Status** on that row — only start it if it says
   `✅ Ready to start`. If it says `⏳ Waiting on...`, pick something else.
3. Put your name in **Owner**, set **Status = In Progress**, fill in
   **Start Date**.
4. Read that task's section in `HANDOFF.md` before writing code.
5. When done: **Status = Done**, fill in **Completed Date**, drop your
   PR link in **PR Link / Notes**.

## Don't touch columns A–E

Predecessor Status is a live formula — typing over it breaks it for that
row. Only edit Status, Owner, Branch Name, Estimate, Start/Completed
Date, and Notes.
