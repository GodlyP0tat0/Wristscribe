# Apple Watch setup

The watch side of WristScribe is an **Apple Watch Shortcut**. A native watchOS app
needs Xcode, which only runs on a Mac. Shortcuts are built on the iPhone and sync to
the watch, so this works from a Windows-only setup.

There are two shortcuts. Build **A** first because it works on every watch, then try **B**.

| | A: Dictate to PC | B: Record to PC |
|---|---|---|
| Speech-to-text | Apple dictation, on the watch | Whisper (Groq/OpenAI), via the laptop |
| Sends | finished text → `/text` | an audio file → `/audio` |
| Cost | free | Groq free tier covers personal use |
| Strengths | instant, always available | better with technical words (uses your `vocabulary` list) |
| Watch support | `Dictate Text` runs on Apple Watch | Apple doesn't document whether `Record Audio` runs on the watch. **Test it.** |

---

## 0. Before you start

1. Start WristScribe on the laptop (`start-wristscribe.bat`). The console shows:
   ```
   Audio URL  : http://192.168.1.23:8765/audio
   Text URL   : http://192.168.1.23:8765/text
   Header     : Authorization: Bearer <your-token>
   ```
2. Put the iPhone on the **same Wi-Fi** as the laptop.
3. **Test the connection first.** In Safari on the iPhone, open the `Check from your
   iPhone's Safari` link from the console. You should see `{"ok": true, ...}`.
   If you don't, see [Troubleshooting](#troubleshooting) before building anything.

## 1. Shortcut A: "Dictate to PC"

On the iPhone, open **Shortcuts** and tap **+**.

1. Tap the name at the top and rename it **Dictate to PC**.
2. Add the action **Dictate Text**. Expand it with the arrow:
   - Language: **English**
   - Stop Listening: **After Pause** (or **On Tap** for long thoughts)
3. Add the action **Get Contents of URL**:
   - URL: your **Text URL**, e.g. `http://192.168.1.23:8765/text`
   - Expand it with the arrow, then set **Method** to **POST**
   - **Headers** → Add new header: Key `Authorization`, Value `Bearer <your-token>`
     (with one space after `Bearer`)
   - **Request Body** → **JSON** → Add new field → **Text**: Key `text`, Value: pick the
     **Dictated Text** variable
4. Open the shortcut's details (the **ⓘ** button, or tap the name → **Details**) and turn
   on **Show on Apple Watch**.
5. Click into a text box on the laptop (Notepad works), then tap **▶** on the iPhone to test.
   When that works, run it from the watch.

## 2. Shortcut B: "Record to PC" (cloud Whisper)

Set an API key first (`api_key` in `config.toml`), then check it on the laptop:
`python -m wristscribe transcribe some-recording.m4a`.

1. New shortcut, named **Record to PC**.
2. Add the action **Record Audio**:
   - Audio Quality: **Normal** (smaller upload, same accuracy for speech)
   - Start Recording: **Immediately**
   - Finish Recording: **On Tap**
3. Add **Get Contents of URL**:
   - URL: your **Audio URL**, e.g. `http://192.168.1.23:8765/audio`
   - Method **POST**, the same `Authorization` header as above
   - **Request Body** → **File** → pick the **Recorded Audio** variable
4. Turn on **Show on Apple Watch**, then test on the iPhone first and on the watch second.

If the watch says the shortcut or one of its actions can't run on Apple Watch, `Record
Audio` is iPhone-only on your watchOS version. Use Shortcut A on the watch, and keep B
for the iPhone.

**Optional feedback:** after Get Contents of URL, add **Get Dictionary Value** (key
`text`) → **Show Result**. The watch then shows what was typed.

## 3. Start it from your wrist in one tap

- **Complication:** touch and hold the watch face → **Edit** → swipe to **Complications** →
  pick a slot → **Shortcuts** → **Dictate to PC**.
- **Siri:** "Hey Siri, Dictate to PC".
- **Apple Watch Ultra:** Settings → **Action Button** → **Shortcut** → **Dictate to PC**.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Safari ping can't connect | Same Wi-Fi? In Windows go to **Settings → Network & internet → Wi-Fi → (your network) → Network profile type → Private**. Then allow Python through the firewall: **Windows Security → Firewall & network protection → Allow an app through firewall → python.exe → Private**. |
| Works at home, not at university/café | Many campus networks (eduroam included) and public networks block device-to-device traffic. Turn on the iPhone's **Personal Hotspot**, connect the laptop to it, restart WristScribe and put the new IP (`172.20.10.x`) in the shortcut. |
| Worked yesterday, not today | The laptop got a new IP. Reserve a fixed IP for it in your router's DHCP settings, or update the URL in the shortcut. |
| `401 Missing or wrong token` | The header value must be exactly `Bearer ` + the token in `config.toml`. |
| `502 ... API key` | Add your key to `config.toml` or set `WRISTSCRIBE_API_KEY`, then restart. |
| Text lands in the wrong window | WristScribe types into whatever has keyboard focus. Click the target text box before you dictate. |
| Clipboard content changed | `paste` mode restores **text** clipboards only. Use `mode = "type"` if you often copy images. |
| An admin app (Task Manager etc.) gets no text | Windows blocks a normal app from typing into elevated apps. Run WristScribe as administrator only if you need this. |

## Security note

Traffic between the watch and the laptop is plain HTTP on your local network. The token
stops strangers from typing on your laptop, but someone on the same Wi-Fi could read
your dictations. Use it on home Wi-Fi or your own hotspot, not public Wi-Fi.
