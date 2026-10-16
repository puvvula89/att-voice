# Architecture and slides

The Cricket Care troubleshooting agent architecture, in three formats built from one layout model.

| File | Use |
|---|---|
| `architecture.html` | Self-contained web page with light and dark themes |
| `architecture.drawio` | Editable diagram; open at app.diagrams.net or in the draw.io desktop app. Icons are embedded. |
| `architecture.pptx` | One editable slide (native shapes), exported from the Google Slides build |
| `build.py` | The layout model and the HTML, draw.io and Slides renderers |
| `slides.py` | Uploads icons, creates or rebuilds the Google Slides deck, renders a thumbnail, exports .pptx |
| `icons/svg`, `icons/png` | Google Cloud icons: SVG for the page and draw.io, PNG for Slides |

## Rebuild

```bash
python3 build.py                                   # architecture.html and architecture.drawio
```

To rebuild the slide and the .pptx you need the Google Workspace CLI (`gws`) logged in with the
`presentations` and `drive.file` scopes.

```bash
python3 slides.py icons --out /tmp/icon-urls.json  # one-time: uploads icons/png to a Drive folder (anyone with link)
python3 build.py --slides /tmp/icon-urls.json      # also writes slides-requests.json
python3 slides.py apply --requests slides-requests.json [--presentation <id>]   # new deck, or rebuild in place
python3 slides.py thumb --presentation <id> --out /tmp/slide.png                # check the layout
python3 slides.py export --presentation <id> --out architecture.pptx
```

The Slides API fetches images by URL, so the icons must be readable by link while the deck is built. The deck keeps
its own copy; the Drive folder can be deleted afterwards.

## Editing

Change coordinates or text in the `FRAMES`, `BOXES`, `EDGES` and `LABELS` lists in `build.py`, then rebuild. Every
element sits on a 1920 x 1080 grid shared by all three outputs.
