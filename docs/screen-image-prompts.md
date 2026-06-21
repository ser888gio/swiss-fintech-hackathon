# Firefly Pixie — Screen Image Generation Prompts

Reference for generating realistic renders of the 3 firmware screens on the
physical Firefly Pixie device. The device is a small ESP32-C3 PCB with a
**240×240 px square TFT display** and four tactile buttons (SW1–SW4) on the
right edge. Background is near-black (`#0d0b0a`). Font is monospace/sans-serif.
Color palette: paper white `#ebeae9`, stone grey `#959190`, orange `#d1671f`,
bright orange `#ef7c24`, brown `#483c35`, safety green `#4ac77d`, safety red
`#cc3322`.

---

## Screen 1 — Standby

### Image generation prompt

```
Photorealistic close-up photograph of a small embedded hardware device, the
"Firefly Pixie", resting on a dark wooden desk. The PCB is matte black with
gold traces visible at the edges. Center stage is a 240×240 square TFT LCD
display showing a dark near-black background (#0d0b0a). On the screen:

  - Top center, small bold uppercase text in stone-grey (#959190):
    "TREASURY VETO"
  - Center, large bold uppercase text in off-white paper (#ebeae9):
    "STANDBY"
  - A small 14×14 px square "breathing" dot in bright orange (#ef7c24),
    centered horizontally below the word STANDBY, softly glowing —
    the dot represents a live-indicator pulse animation frozen mid-breath
    at about 60% opacity.
  - Near bottom center, small text in stone-grey (#959190):
    "Waiting for transaction"

The display has a faint glass reflection. Four small tactile push-buttons
are visible on the right edge of the PCB, labeled SW1 (top) through SW4
(bottom) in tiny white silkscreen text. A USB-C cable is plugged into the
bottom of the board. Shallow depth of field, soft studio lighting, 4K detail.
```

### Key UI elements
| Element | Value |
|---------|-------|
| Background | `#0d0b0a` |
| "TREASURY VETO" | small bold, `#959190`, top-center |
| "STANDBY" | large bold, `#ebeae9`, center |
| Live dot | 14×14 px, `#ef7c24`, pulsing ~60% opacity |
| "Waiting for transaction" | small, `#959190`, lower-center |

---

## Screen 2 — Payment Verification (Match Code)

### Image generation prompt

```
Photorealistic close-up of the Firefly Pixie PCB held in a person's hand,
screen lit up showing a payment approval prompt. The 240×240 TFT display
shows on a near-black background (#0d0b0a):

  - Top center, small bold uppercase stone-grey text: "VERIFY PAYMENT"
  - Below that, medium bold off-white text: "125000.50 USD"
  - Smaller stone-grey text: "rPT1Sjq2..pAYe"  (truncated XRPL address)
  - Even smaller stone-grey text: "XRPL Testnet"

  - A rectangular "chip" element centered horizontally, dark brown
    background (#211d1b), 150×46 px, with a thin 3 px bright orange
    (#d1671f) accent bar along the top edge. Inside the chip:
      - Small uppercase stone-grey label: "MATCH CODE"
      - Large bold spaced digits in bright orange (#ef7c24): "6  4  3  5"
        (digits spaced apart like a PIN display)

  - Near the bottom, small stone-grey text: "SW2 refresh code"
  - Bottom-left, small bold green (#4ac77d) text: "SW4 APPROVE"
  - Bottom-right, small bold red (#cc3322) text: "SW1 REJECT"

The four physical push-buttons on the right edge of the PCB are visible.
SW4 (bottom button) is slightly depressed, being pressed by the operator's
thumb. The screen glow illuminates the operator's fingers. Dark ambient
environment, single overhead desk lamp, 4K macro photography.
```

### Key UI elements
| Element | Value |
|---------|-------|
| "VERIFY PAYMENT" | small bold, `#959190`, top-center |
| Amount | medium bold, `#ebeae9` |
| Destination | small, `#959190`, truncated |
| Chip background | `#211d1b`, 150×46 px |
| Chip accent bar | 3 px, `#d1671f` |
| "MATCH CODE" label | small, `#959190` |
| Match digits | large bold, `#ef7c24`, spaced e.g. `6  4  3  5` |
| SW4 APPROVE | small bold, `#4ac77d`, bottom-left |
| SW1 REJECT | small bold, `#cc3322`, bottom-right |

---

## Screen 3a — Result: APPROVED

### Image generation prompt

```
Photorealistic macro photograph of the Firefly Pixie device sitting on a
metal desk in a corporate treasury office. The 240×240 square TFT display
shows on a near-black background:

  - Top center, small bold stone-grey uppercase text: "TREASURY VETO"
  - Center of screen, very large bold uppercase text in vivid safety
    green (#4ac77d): "APPROVED"
    The text glows slightly against the dark background, conveying
    a sense of confirmation and relief.
  - Just below center, small stone-grey text: "Signing…"

The buttons on the right side of the PCB are unlit/untouched. The screen
brightness casts a green tint onto the surrounding PCB surface. Clean
minimal composition, shallow depth of field, soft diffused studio light.
```

---

## Screen 3b — Result: REJECTED

### Image generation prompt

```
Photorealistic macro photograph of the Firefly Pixie device on a dark desk.
The 240×240 TFT display shows:

  - Top center, small bold stone-grey uppercase text: "TREASURY VETO"
  - Center, very large bold uppercase text in safety red (#cc3322):
    "REJECTED"
    The red glow reflects off the PCB surface and the operator's hand
    nearby.
  - Below center, small stone-grey text: "Payment blocked"

The composition conveys a decisive veto — the red screen is dramatic and
deliberate. Dark moody lighting with only the screen as the light source.
The USB cable is visible trailing off frame. Cinematic macro photography, 4K.
```

---

## Screen 3c — Result: EXPIRED

### Image generation prompt

```
Photorealistic photograph of the Firefly Pixie device. The 240×240 TFT
display shows:

  - Top center, small bold stone-grey uppercase text: "TREASURY VETO"
  - Center, large bold uppercase text in muted stone-grey (#959190):
    "EXPIRED"
  - Below center, small stone-grey text: "No decision in time"

The muted grey palette of the expired screen feels neutral and cold —
no approval, no rejection, just a timeout. Soft even lighting, the device
sits on a light-grey desk surface. 4K product photography style.
```

---

## Full device render (all 3 screens side by side)

### Image generation prompt

```
Product photography layout: three Firefly Pixie PCB devices arranged side
by side on a dark slate surface, each displaying a different firmware screen:

LEFT device — Standby screen:
  Dark background, "TREASURY VETO" in grey at top, "STANDBY" in large
  off-white text, pulsing orange dot below, "Waiting for transaction" at bottom.

CENTER device — Payment verification screen:
  "VERIFY PAYMENT" header, "125000.50 USD" amount, truncated XRPL address,
  a dark chip with "MATCH CODE" and large orange digits "6  4  3  5",
  green "SW4 APPROVE" and red "SW1 REJECT" labels at the bottom.

RIGHT device — Approved screen:
  "TREASURY VETO" header, giant "APPROVED" in safety green dominating the
  screen, "Signing…" subtitle below.

All three PCBs are identical matte black boards with gold traces, four
tactile buttons on the right edge, USB-C port at the bottom. Each screen
casts a different colored glow (neutral / orange / green) onto the desk
surface. Soft top-down studio lighting, slight 3/4 angle perspective,
4K commercial product photography.
```
