# Typed suite run 20261021T035424Z

App `projects/tmeg-working-demos/locations/us/apps/cricket-care`

| Scenario | Title | Result | Tools seen | Missing | Forbidden hit |
|---|---|---|---|---|---|
| P1 | Line suspended for non-payment | PASS | transfer_to_agent, get_progress, get_lines, get_sim_status, get_line_status, check_outage, search_tutorials | - | - |
| P2 | Tower outage at the caller's zip | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, get_sim_status, check_outage, search_tutorials | - | - |
| P3 | Clean account, Wi-Fi slow on the iPhone | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, check_outage, search_tutorials, next_step | - | - |
| P4 | Galaxy will not power on, calling from the iPhone line | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, search_tutorials, next_step | - | - |
| P5 | Caller wants only the link | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, search_tutorials, send_guide_link | - | - |
| P6 | Caller names a device not on the account | PASS | transfer_to_agent, get_progress, get_lines | - | - |
| P7 | Fix fails after the full article | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, get_data_usage, search_tutorials, open_ticket | - | - |
| P8 | Call drops at the restart and the caller rings back | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, check_outage, search_tutorials, next_step, get_data_usage | - | - |

## Transcripts

### P1 — Line suspended for non-payment (sessions `0b8d6859-d33a-4a67-9aa5-7d68f9a1ffef`)
- **Caller (call 1):** my calls keep failing
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this phone
  **Agent:** Let me check a couple of things on our side first.
Everything looks normal on our side. I'll search for a fix.
I have a guide that can help. I can text it to you, walk you through it now, or both. What works for you?
  _tools: support_get_sim_status, support_get_line_status, support_check_outage, search_tutorials_

### P2 — Tower outage at the caller's zip (sessions `1efd3813-0321-4f84-9b32-12f352230bc9`)
- **Caller (call 1):** I have no service at all right now
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes
  **Agent:** Let me check a couple of things on our side first.
Everything looks normal on our side. It might be a setting on your iPhone.
I have a guide that walks through manually selecting a network. I can text you the guide, walk you through it now, or both. What works for you?
  _tools: support_get_line_status, support_get_sim_status, support_check_outage, search_tutorials_

### P3 — Clean account, Wi-Fi slow on the iPhone (sessions `9807eda5-64f6-4c8d-af4b-0dee210adb33`)
- **Caller (call 1):** my wifi is really slow
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this iPhone
  **Agent:** "Slow Wi-Fi, got it. Let me check a couple of things on our side first."
Everything looks normal on our side. It might be a setting on your iPhone.
I have a guide for Wi-Fi slowdowns. I can text it to you, walk you through it now, or both. What works?
  _tools: support_get_line_status, support_check_outage, search_tutorials_
- **Caller (call 1):** walk me through it
  **Agent:** Great. We'll go through a few steps to troubleshoot, like checking your connection and resetting network settings. To start, please confirm your Wi-Fi connection. Do you see the Wi-Fi icon at the top of your screen?
  _tools: next_step_
- **Caller (call 1):** done, next
  **Agent:** Open Settings and tap Wi-Fi. Do you see a blue checkmark next to your network name?
  _tools: next_step_

### P4 — Galaxy will not power on, calling from the iPhone line (sessions `99765a72-8f91-4551-b380-eef72bfd3b75`)
- **Caller (call 1):** my galaxy won't turn on at all
  **Agent:** I understand. Is that the Galaxy A15?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** it's the second line
  **Agent:** Great. I can walk you through some steps to get it powered back on. I'll check a few things first.
Everything looks normal on our side. I can walk you through a guide to get your Galaxy turning on again, or I can text it to you. What works best?
  _tools: support_check_outage, support_get_line_status, search_tutorials_
- **Caller (call 1):** ok what do I do
  **Agent:** "I'm going to walk you through some steps to get your phone turned back on."
"Are you having issues powering off your phone, or powering it on?"
  _tools: next_step_

### P5 — Caller wants only the link (sessions `6ab83c49-fa5c-4fbd-943a-0c11e11f9344`)
- **Caller (call 1):** my iphone bluetooth won't pair, just text me the guide
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes, this iPhone
  **Agent:** I was unable to send that text. I can walk you through it now instead.
  _tools: support_check_outage, support_get_line_status, search_tutorials, support_send_guide_link_

### P6 — Caller names a device not on the account (sessions `83aedf05-2f4e-4ce7-9c39-bf9acfc96cdc`)
- **Caller (call 1):** my pixel 9 screen is frozen
  **Agent:** "Which phone has the frozen screen? Is it the iPhone or the Galaxy?"
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** I'm sure it's a pixel
  **Agent:** "Could you read me the model number from Settings? I can only see an iPhone and a Galaxy on your account."

### P7 — Fix fails after the full article (sessions `454568a6-35f1-47a7-a7a5-582834027675`)
- **Caller (call 1):** data is crawling on my iphone
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes
  **Agent:** So your data is crawling. Let me check a couple of things on our side first.
Everything looks normal on our side. It might be a setting on your iPhone.
Could you tell me more about what's happening? For example, is it slow everywhere, or just inside certain buildings?
  _tools: support_check_outage, support_get_line_status, support_get_data_usage, search_tutorials_
- **Caller (call 1):** did that, still slow
  **Agent:** Let me search again with that in mind.
I can walk you through checking your data settings. I can text you the guide, walk you through it now, or both. What works for you?
  _tools: search_tutorials_
- **Caller (call 1):** did that too, still slow
  **Agent:** Understood. I can walk you through checking your 5G and LTE settings instead. I can text you the guide, walk you through it, or both. Which do you prefer?
- **Caller (call 1):** nothing worked
  **Agent:** I can open a support ticket for you. A store visit is also a faster option. I'll open that ticket now.
I've opened a ticket, number T-1001. A specialist will call you within one business day. You can also visit a store sooner. Is there anything else?
  _tools: support_open_ticket_

### P8 — Call drops at the restart and the caller rings back (sessions `59e44f5d-9b86-434c-a9c2-730f7004a791`, `6a4273b5-45c1-4683-984b-24053d8267ef`)
- **Caller (call 1):** my wifi is really slow
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this iPhone
  **Agent:** "Slow Wi-Fi, got it. Let me check a couple of things on our side first."
Everything looks normal on our side. I have a guide that can help fix Wi-Fi connection issues or slowdowns. I can text you the guide, walk you through it now, or both. What works for you?
  _tools: support_get_line_status, support_check_outage, search_tutorials_
- **Caller (call 1):** walk me through it
  **Agent:** We'll go through a few steps to troubleshoot, like confirming your connection and restarting. To start, let's make sure Wi-Fi is on. Open Settings and tap Wi-Fi. Is the switch green?
  _tools: next_step_
- **Caller (call 1):** done
  **Agent:** Take your time. Say ready when you're on that screen.
- **Caller (call 1):** done
  **Agent:** Just checking in. Are you on the Wi-Fi screen?
- **Caller (call 1):** done
  **Agent:** To continue, I'll need to know if the Wi-Fi switch is green. Let me know when you see that.
- **Caller (call 1):** yes, I'm okay to call back
  **Agent:** No, that step does not disconnect us. Just let me know if the Wi-Fi switch is green.
- **Caller (call 2):** hi, I'm calling back
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 2):** no, it's still slow
  **Agent:** "I understand, you're calling about the Galaxy. Before we get started, I need to check a couple of things on our side."

Everything looks normal on our side. When you say it's slow, is that when you're browsing on Wi-Fi or using mobile data?
  _tools: support_get_line_status, support_get_data_usage, support_check_outage_
