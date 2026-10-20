# Typed suite run 20261019T235207Z

App `projects/river-vigil-507817-e7/locations/us/apps/cricket-care`

| Scenario | Title | Result | Tools seen | Missing | Forbidden hit |
|---|---|---|---|---|---|
| P1 | Line suspended for non-payment | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, get_sim_status | - | - |
| P2 | Tower outage at the caller's zip | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status | - | - |
| P3 | Clean account, Wi-Fi slow on the iPhone | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, search_tutorials, next_step | - | - |
| P4 | Galaxy will not power on, calling from the iPhone line | PASS | transfer_to_agent, get_progress, get_lines, get_line_status, check_outage, search_tutorials, next_step | - | - |
| P5 | Caller wants only the link | FAIL | transfer_to_agent, get_progress, get_lines | search_tutorials, send_guide_link | - |
| P6 | Caller names a device not on the account | PASS | transfer_to_agent, get_progress, get_lines | - | - |
| P7 | Fix fails after the full article | PASS | transfer_to_agent, get_progress, get_lines, get_data_usage, check_outage, get_line_status, search_tutorials, open_ticket | - | - |
| P8 | Call drops at the restart and the caller rings back | PASS | transfer_to_agent, get_progress, get_lines, check_outage, get_line_status, search_tutorials, next_step, save_progress | - | - |

## Transcripts

### P1 — Line suspended for non-payment (sessions `1418550b-1d2e-46c2-b3f0-0a008b1ca87a`)
- **Caller (call 1):** my calls keep failing
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this phone
  **Agent:** "Let me check a couple of things on our side first."
I see your line is suspended because the payment is past due. I can connect you to billing to resolve that.
  _tools: support_check_outage, support_get_line_status, support_get_sim_status_

### P2 — Tower outage at the caller's zip (sessions `05a281f2-974b-4f80-a0f3-e06bea965b97`)
- **Caller (call 1):** I have no service at all right now
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes
  **Agent:** Got it, no service at all on your iPhone. Let me check a couple of things on our side first.
It looks like there's a network outage in your area that started around 7 AM today. We expect to have it fixed by 11 AM, so your phone is fine.
  _tools: support_check_outage, support_get_line_status_

### P3 — Clean account, Wi-Fi slow on the iPhone (sessions `2659f96b-942f-45cd-8fc3-b9262bae4a5f`)
- **Caller (call 1):** my wifi is really slow
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this iPhone
  **Agent:** Thanks. Let me check a couple of things on our side first.
Everything looks normal on our side. It might be a setting on your iPhone.
I have a guide for troubleshooting slow Wi-Fi. I can text it to you, walk you through it now, or both. What works?
  _tools: support_check_outage, support_get_line_status, search_tutorials_
- **Caller (call 1):** walk me through it
  **Agent:** Alright, let's start. First, we'll try a few things like checking your connection, restarting, and resetting network settings.
Go to Settings, then tap Wi-Fi. Do you see a blue checkmark next to your network?
  _tools: next_step, next_step_
- **Caller (call 1):** done, next
  **Agent:** Thanks. Now, we'll try turning off Connectivity Assist. This will make sure your phone isn't trying to use cellular data instead of Wi-Fi. From Settings, tap Cellular, then scroll down and turn off Wi-Fi Assist. Let me know when that's done.
  _tools: next_step_

### P4 — Galaxy will not power on, calling from the iPhone line (sessions `4d5dbb49-bb79-498b-881c-e35687c821a0`)
- **Caller (call 1):** my galaxy won't turn on at all
  **Agent:** I understand your Galaxy won't turn on. Let me check a couple of things on our side first.
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** it's the second line
  **Agent:** Everything looks normal on our side. I have a guide that can help when your Galaxy won't turn on.

I can text you the link, walk you through it now, or both. What works for you?
  _tools: support_get_line_status, support_check_outage, search_tutorials_
- **Caller (call 1):** ok what do I do
  **Agent:** This guide will walk us through troubleshooting. Are you having issues powering off your phone, or powering it on?
  _tools: next_step_

### P5 — Caller wants only the link (sessions `3e4bdc4a-2ceb-425e-bf02-158fb19242a3`)
- **Caller (call 1):** my iphone bluetooth won't pair, just text me the guide
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_

### P6 — Caller names a device not on the account (sessions `c150b601-b39d-4784-a8d8-6bf837ea7342`)
- **Caller (call 1):** my pixel 9 screen is frozen
  **Agent:** I see. I'll check a couple of things first. Is that the iPhone or the Galaxy?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** I'm sure it's a pixel
  **Agent:** Sorry for the mix-up. Could you please open Settings on that phone and read me the model name? This helps me find the right steps.

### P7 — Fix fails after the full article (sessions `50d42f54-17a3-4019-a89e-873109f97a67`)
- **Caller (call 1):** data is crawling on my iphone
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes
  **Agent:** So data is very slow on your iPhone. Let me check a couple of things on our side first.
It looks like your high-speed data is all used up for this cycle. Your speeds are reduced until October 28th. Would you still like to try device steps?
  _tools: support_get_data_usage, support_check_outage, support_get_line_status_
- **Caller (call 1):** did that, still slow
  **Agent:** The slower speeds are due to reaching your data limit. We can still run through some steps on your iPhone if you think it's something else.
(The tool search_tutorials failed to return any results. Therefore, I'll offer to text the guide, but since I don't have its details, I'll just offer to try some steps.)

I'm not finding a specific guide for that right now. We can try some basic steps together if you like.
  _tools: search_tutorials_
- **Caller (call 1):** did that too, still slow
  **Agent:** We could open a support ticket to have this looked into further. Or visiting a store might get you a faster solution.
I've opened ticket T-1001 for you. A specialist will call back within one business day.
  _tools: support_open_ticket_
- **Caller (call 1):** nothing worked
  **Agent:** I understand your frustration. Since we've exhausted the troubleshooting, visiting a store might be the next best step for hands-on help. Would you like me to find the nearest location?

### P8 — Call drops at the restart and the caller rings back (sessions `86493776-5178-415a-93ab-fce1a1223b30`, `9fe44cd3-520d-4fe4-827a-cf2c71201e50`)
- **Caller (call 1):** my wifi is really slow
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_progress, support_get_lines_
- **Caller (call 1):** yes it's this iPhone
  **Agent:** Got it, let me check a couple of things on our side first. Everything looks normal here.
I have a guide that can help with slow Wi-Fi speeds. I can text it to you, walk you through it now, or both. What works for you?
  _tools: support_check_outage, support_get_line_status, search_tutorials_
- **Caller (call 1):** walk me through it
  **Agent:** To start, there are several steps we can take, like confirming your connection and restarting your iPhone. Let's begin by making sure you're connected to Wi-Fi.
Within the Settings app, please confirm your iPhone is connected to a Wi-Fi network. You should see a blue checkmark next to your active connection.
  _tools: next_step, next_step_
- **Caller (call 1):** done
  **Agent:** Let's try turning off Connectivity Assist. Do you see Cellular within your Settings app?
  _tools: next_step_
- **Caller (call 1):** done
  **Agent:** This next step will disconnect our call. I'll save your place so we can pick up right after it when you call back. Please confirm by saying you're okay to call back.
  _tools: next_step, support_save_progress_
- **Caller (call 1):** done
  **Agent:** I need your confirmation before we run this step. Are you okay to call back?
- **Caller (call 1):** yes, I'm okay to call back
  **Agent:** Alright. Go ahead and restart your iPhone, then call us back.
  _tools: next_step_
- **Caller (call 2):** hi, I'm calling back
  **Agent:** Welcome back, I saved your place. Did restarting your iPhone fix the Wi-Fi issue?
  _tools: transfer_to_agent, support_get_progress_
- **Caller (call 2):** no, it's still slow
  **Agent:** This next step will disconnect our call. I'll save your place so we can pick up right after it when you call back. Please confirm by saying you're okay to call back.
  _tools: next_step, support_save_progress_
