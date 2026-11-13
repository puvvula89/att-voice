# Talk track: how a tutorial gets from the website to the conversation

Reference notes for the demo. Two flows: loading the content (done once, offline) and using it in a
call or chat.

## 1. Loading the content

```
 Cricket device tutorials            knowledge/                         Google Cloud
 (public website)
┌──────────────────────┐   ┌────────────────────────────────┐   ┌──────────────────────────┐
│ one page per guide,  │   │ 1 EXTRACT   headless browser   │   │ private bucket           │
│ per phone            │──▶│   opens each guide, clicks     │   │   step pictures          │
│                      │   │   through every step and choice│   │                          │
│ steps, choices,      │   │                                │──▶│ Agent Search data store  │
│ pictures, links to   │   │ 2 LABEL     Gemini marks each  │   │   one record per guide   │
│ other guides         │   │   step: ends the call, may     │   │   995 guides, 5 phones   │
└──────────────────────┘   │   drop it, or safe; adds       │   │   searchable: title,     │
                           │   symptoms and a summary       │   │   summary, symptoms      │
                           │                                │   │   filter: phone          │
                           │ 3 BUILD     one catalog file   │   │   steps travel packed    │
                           │   per phone, plus a hand review│   │   inside the record      │
                           │   of the risky steps           │   └──────────────────────────┘
                           │                                │
                           │ 4 LOAD      pictures to the    │
                           │   bucket, records to the store │
                           └────────────────────────────────┘
```

All four steps are our own code in `knowledge/`. Nothing is scraped at demo time: the tutorials are
in the repository and `deploy/content.sh` runs steps 3 and 4.

## 2. What extraction does with a guide that branches

Example: "Can't send or receive texts" on the Galaxy A15 5G. On the website it is a tree: the first
step asks a question, and the answer decides which steps follow.

```
 On the website                                  After extraction: one flat path per answer

            ┌──────────────────────┐             path A   choices: ["Can't send texts"]
            │ 1 Intro: which one?  │               1 Intro
            └──────────┬───────────┘               2 Signal or data connection
            ┌──────────┴───────────┐               3 Airplane mode
            ▼                      ▼               4 The message is too large
   "Can't send texts"     "Can't receive texts"    5 Recipient is blocked
            │                      │
   2 Signal               2 Signal               path B   choices: ["Can't receive texts"]
   3 Airplane mode        3 Airplane mode          1 Intro
   4 Message too large    4 Do Not Disturb         2 Signal or data connection
   5 Recipient blocked    5 Storage is full        3 Airplane mode
                          6 Sender is blocked      4 Do Not Disturb
                          7 Texts going to         5 Storage is full
                            another device         6 Sender is blocked
                                                   7 Texts going to another device
```

The extractor clicks each answer in turn and records the steps that appear, so every route through
the guide becomes its own numbered list. A second question further down would simply give more
paths, each with two choices. Every step keeps its text, notes, picture, links to other guides, and
its risk label.

## 3. Using it in a call or chat

```
 Caller: "I'm not getting texts"
        │
        ▼
 ┌─────────────────┐  which phone?   ┌──────────────────────────────────────────────┐
 │ Greeting agent  │────────────────▶│ Troubleshooting agent                        │
 │ (saved place?   │                 │                                              │
 │  → welcome back)│                 │ 1 account: lines, line status, outage check  │
 └─────────────────┘                 │ 2 search the data store, this phone only     │
                                     │ 3 offer: text or link, walk-through, or both │
                                     │ 4 walk: one step per turn                    │
                                     │      asks the guide's question → picks path  │
                                     │      before a step that ends the call:       │
                                     │        save the place, warn, wait for "ok"   │
                                     │ 5 not fixed → support ticket                 │
                                     └──────────────────────────────────────────────┘
        voice: spoken wording                 chat: step heading, picture, quick replies
```

Points worth saying out loud:

- **One agent, two channels.** The same app answers the phone and the web chat; only the wording and
  the extras (pictures, quick replies, link card) change.
- **Account first, device second.** The line and outage checks run before any step on the phone, so
  the caller is not sent through settings when the problem is on the network side.
- **The model words each step; code keeps the place.** The step text comes from Cricket's guide, the
  agent says it naturally, and a small tool decides which step is next, so steps cannot be skipped
  or repeated.
- **Calls that drop are expected.** Before a restart or network reset the place is saved; the next
  call opens with "Welcome back" and continues from that step.
