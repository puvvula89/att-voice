# Typed suite run 20261017T022831Z

App `projects/river-vigil-507817-e7/locations/us/apps/cricket-care`

| Scenario | Title | Result | Tools seen | Missing | Forbidden hit |
|---|---|---|---|---|---|
| P1 | Line suspended for non-payment | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, check_outage | - | - |
| P2 | Tower outage at the caller's zip | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, get_sim_status | - | - |
| P3 | Clean account, Wi-Fi slow on the iPhone | FAIL | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, find_tutorials, get_tutorial | get_step | - |
| P4 | Galaxy will not power on, calling from the iPhone line | FAIL | transfer_to_agent, get_progress, get_lines, find_tutorials, get_tutorial | get_step | - |
| P5 | Caller wants only the link | PASS | transfer_to_agent, get_progress, get_lines, find_tutorials, get_tutorial, send_guide_link | - | - |
| P6 | Caller names a device not on the account | PASS | transfer_to_agent, get_progress, get_lines | - | - |
| P7 | Fix fails after the full article | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, check_outage, get_data_usage, find_tutorials, get_tutorial | - | - |

## Transcripts

### P1 — Line suspended for non-payment (session `e68ab957-8701-44ce-8f40-d81e318b6341`)
- **Caller:** my calls keep failing
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** yes it's this phone
  **Agent:** So calls are failing. Let me check a couple of things on our side first.
I can see that your line is suspended because the payment is past due. I can connect you to billing to take care of that.
  _tools: support_get_line_status, support_check_outage_

### P2 — Tower outage at the caller's zip (session `f02e9a36-6e13-447c-8513-55bc2db2bab2`)
- **Caller:** I have no service at all right now
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** yes
  **Agent:** It looks like there's an outage in your area. It started around 7:10 AM and we expect it to be fixed by 11:00 AM. Your phone should be fine.
  _tools: support_check_outage, support_get_line_status, support_get_sim_status_

### P3 — Clean account, Wi-Fi slow on the iPhone (session `2b8529d4-7e53-4d25-8ab3-f6d36dd7c639`)
- **Caller:** my wifi is really slow
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** yes it's this iPhone
  **Agent:** Okay, your Wi-Fi is slow on your iPhone. Let me check a couple of things on our side first.
Everything looks normal on our side. It might be a setting on your phone.
This guide helps with slow Wi-Fi speeds. It has seven steps and takes about five minutes. I can text you the guide, walk you through it now, or both. What works for you?
  _tools: support_check_outage, support_get_line_status, support_find_tutorials, support_get_tutorial_
- **Caller:** walk me through it
  **Agent:** Alright, first open Settings and confirm you're connected to a Wi-Fi network. Do you see a blue checkmark next to your active connection?
- **Caller:** done, next
  **Agent:** For the next step, we'll try turning off Connectivity Assist. Your iPhone might be trying to use cellular data instead of Wi-Fi. Do you see that option?

### P4 — Galaxy will not power on, calling from the iPhone line (session `1f98c55e-d90e-4c51-9a4d-60df604adfe9`)
- **Caller:** my galaxy won't turn on at all
  **Agent:** I understand. Is that the Galaxy A15?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** it's the second line
  **Agent:** Right. I can help with that. Let's check a couple of things on our side first.
I can text you the guide, walk you through it now, or both. What works for you?
  _tools: support_find_tutorials, support_get_tutorial, support_get_tutorial_
- **Caller:** ok what do I do
  **Agent:** We'll try powering it on first. Press and hold the Power button until the logo appears.

### P5 — Caller wants only the link (session `dda30799-a3f1-41ce-91cf-1adfd630ae23`)
- **Caller:** my iphone bluetooth won't pair, just text me the guide
  **Agent:** I understand you're calling about your iPhone. I can't send texts right now, but I can read you the link or walk you through it. What works for you?
  _tools: transfer_to_agent, support_get_progress, support_get_lines, support_find_tutorials, support_get_tutorial, support_send_guide_link_

### P6 — Caller names a device not on the account (session `43a07768-a54b-40d8-9c5e-a3cbb9ae4000`)
- **Caller:** my pixel 9 screen is frozen
  **Agent:** Your screen is frozen, I understand. Which phone is that, the iPhone or the Galaxy?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** I'm sure it's a pixel
  **Agent:** Sorry. You'll need to read me the model from Settings before we can switch. For now, let's check the lines I see here. Is it your iPhone or the Galaxy?

### P7 — Fix fails after the full article (session `0f9199d5-2859-4a66-b110-c0903e5d2e38`)
- **Caller:** data is crawling on my iphone
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller:** yes
  **Agent:** So data is crawling on your iPhone. Let me check a couple of things on our side first.
You've used all your high-speed data for this month. It will reset on October 28th, but we can still try device steps if you want.
  _tools: support_get_line_status, support_check_outage, support_get_data_usage_
- **Caller:** did that, still slow
  **Agent:** Okay, I have a guide that can help. It involves toggling your mobile data off and back on, which takes about a minute.

I can text you the guide, walk you through it now, or both. What works for you?
  _tools: support_find_tutorials, support_get_tutorial_
- **Caller:** did that too, still slow
  **Agent:** It's likely your speeds are slow because you've used all your high-speed data, as we saw. Since we've ruled out basic settings, I can open a support ticket to have this looked into further, or we can discuss upgrading your plan. Which would you prefer?
- **Caller:** nothing worked
  **Agent:** Understood. Since your high-speed data is used up, that's the most likely cause. I can open a support ticket for you, or you can also visit a store for faster help. Which would you prefer?
