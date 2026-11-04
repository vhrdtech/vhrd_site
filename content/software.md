+++
title = "Software"
description = "IOWeaver, the protocol analyzer and grapher; RockFace, the firmware debugger; mx3, parts, BOMs and assembly for an electronics lab."

[extra]
label = "Software"
sig = "usb"
+++

Three tools for the bench: one plots what a device says, one debugs the firmware that says it, one keeps the parts and the boards in order. <span class="v-badge">draft</span>

## IOWeaver

{{ <vh.fig stem="img/screens/ioweaver" widths={[1280]} sizes="(max-width: 75rem) 100vw, 72rem" alt="IOWeaver screenshot" n="1" caption="IOWeaver: protocol analyzer and grapher" /> }}

A protocol analyzer and grapher for the desktop: it records, decodes, shows on a timeline and sends the traffic of a device. It is the GUI for {{ <vh.ref name="Pinsmith" /> }} and {{ <vh.ref name="Donguru" /> }} and ships with them.

{{ <vh.specs items={["Record: I2C, CAN, UART, GPIO, WireWeaver", "Decode: the same protocols", "Show: on a timeline, and plot", "Send: back to the device"]} /> }}

## RockFace

{{ <vh.fig stem="img/lab/rockface/rockface-window" widths={[640, 1280]} sizes="(max-width: 75rem) 100vw, 72rem" alt="RockFace window: timeline view, log view and defmt counters" n="2" caption="RockFace: firmware debugger, timeline and logs" /> }}

A tracer and debugger for embedded firmware, for systems that are running. Commercial release: TBD.

{{ <vh.specs items={["Logs: from one board or a fleet", "Graphs: stack and CPU use", "Profiling: zero-cost", "Timeline: sleep spans and events"]} /> }}

## mx3

The electronics side of an in-house lab system: from a BOM to parts on the shelf to an assembled board.

<div class="fig-pair">

{{ <vh.fig stem="img/lab/mx3/mx3-assemble" widths={[640, 1280]} sizes="(max-width: 52rem) 100vw, 36rem" alt="mx3 PCB Assemble tab: each BOM line with its designators, the part to place and the stock left" n="3" caption="mx3: guided PCB assembly" /> }}
{{ <vh.fig stem="img/lab/mx3/mx3-bom-editor" widths={[640, 1280]} sizes="(max-width: 52rem) 100vw, 36rem" alt="mx3 BOM Editor tab: a capacitor line with its part choices, stock and Digi-Key parameters" n="4" caption="mx3: BOM editor" /> }}

</div>

{{ <vh.fig stem="img/lab/mx3/mx3-bom-cost" widths={[640, 1280]} sizes="(max-width: 75rem) 100vw, 72rem" alt="mx3 BOM Cost tab: a chart of the cost per BOM line and a table of each line's unit price from 1 to 5k pieces" n="5" caption="mx3: BOM cost at every price break" /> }}

- BOM import from CSV or XLSX, with each line mapped to a part automatically.
- A BOM editor: part choices, variants, stock and box per line, cost with a price chart, a purchase list.
- A parts database with typed parameters and parametric search.
- Digi-Key pricing and stock for every part, with their history, kept fresh by a background crawler.
- A warehouse: boxes in boxes, stock, photos and a barcode scanner.
- Guided manual PCB assembly: it plans the placement and records every part that moves.

mx3 runs in VHRD's own lab today. It may be opened up or offered as a product later.
