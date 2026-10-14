# Typed suite run 20261014T003418Z

App `projects/river-vigil-507817-e7/locations/us/apps/cricket-care`

| Scenario | Title | Result | Tools seen | Missing | Forbidden hit |
|---|---|---|---|---|---|
| P1 | Line suspended for non-payment | PASS | transfer_to_agent, get_lines, get_line_status, check_outage, get_sim_status | - | - |

## Transcripts

### P1 — Line suspended for non-payment (session `9706a8fc-c800-453a-8993-291fde902b80`)
- **Caller:** my calls keep failing
  **Agent:** I see you're calling from your iPhone. Is that the one having trouble?
  _tools: transfer_to_agent, support_get_lines_
- **Caller:** yes it's this phone
  **Agent:** I am sorry to see that your line is suspended because the payment is past due. I can connect you to billing now to get that sorted out.
  _tools: support_get_line_status, support_check_outage, support_get_sim_status_
