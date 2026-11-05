+++
title = "FAQ"
description = "Answers about buying Donguru and Pinsmith, open source, working with VHRD, and how this site handles cookies, tracking and e-mail."

[extra]
label = "FAQ"
headline = "Questions and answers"
sig = "ctrl"
+++

## The products

<details><summary>When can I buy Donguru or Pinsmith?</summary><p id="buy">Both launch on Crowd Supply. {{ <vh.ref name="Donguru" /> }} comes first, in Q1–Q2 2027; {{ <vh.ref name="Pinsmith" /> }} after it. Prices are not set yet. <a href="{{ get_url(path='/donguru/', trailing_slash=true) }}#notify">Get notified</a> and you hear when the campaign opens.</p></details>

<details><summary>Why Crowd Supply and not Kickstarter?</summary><p id="crowd-supply">Crowd Supply is made for open-source electronics. They check every project before it goes up, and after the campaign they keep selling it.</p></details>

<details><summary>Is it open source?</summary><p id="open-source">Yes, all of it: the schematics, the board files, the firmware and the software. You can read how the protection works, change it, and keep using the board without VHRD. The licences are named on each repository.</p></details>

<details><summary>Which computers do the tools work on?</summary><p id="computers">The desktop tools — {{ <vh.ref name="IOWeaver" /> }} and {{ <vh.ref name="RockFace" /> }} — and the command-line tools, <code>dg</code>, <code>cnt</code>, <code>ww</code> and <code>bedrock-lint</code>, run on Linux, Windows and macOS. The Rust libraries build wherever Rust does.</p></details>

<details><summary>Where do you ship?</summary><p id="shipping">Anywhere a carrier delivers and VHRD may legally ship to. Campaign orders go out through Crowd Supply; the boards in <a href="{{ get_url(path='/shop/', trailing_slash=true) }}">the shop</a> are ordered by mail for now.</p></details>

## Working with VHRD

<details><summary>Can you design a board or firmware for my project?</summary><p id="design-work">Sometimes. Most of my time goes into VHRD's own products, so I take outside work only when a slot opens. The <a href="{{ get_url(path='/services/', trailing_slash=true) }}">services page</a> says what I do and how to ask.</p></details>

<details><summary>Where do I get help, or report a bug?</summary><p id="help">For the open-source libraries and tools, open an issue in that repository on GitHub. A support route for the products comes with the launch. Until then, write as the <a href="{{ get_url(path='/services/', trailing_slash=true) }}">services page</a> describes: I read everything, but I can't promise a quick answer.</p></details>

<details><summary>Who is behind VHRD?</summary><p id="who">Me, Roman Isaikin, in Asker, Norway. I design the boards, write the firmware and build the software. The company is VHRD.TECH AS. More on <a href="{{ get_url(path='/about/', trailing_slash=true) }}">the about page</a>.</p></details>

## The site

<details><summary>Why is there no cookie banner?</summary><p id="cookies">Because there is nothing to ask you about. This site sets no cookies, runs no analytics or tracking, and loads nothing from other companies' servers: the fonts, pictures and scripts all come from vhrd.tech. The only thing your browser keeps is your light or dark choice, and only after you press the toggle. A banner would only be needed to ask permission for things this site doesn't do.</p></details>

<details><summary>Do you track me?</summary><p id="tracking">No. There is no analytics script, no tracking pixel and no ad network. The server keeps ordinary access logs (address, time, page) to keep the site running and safe, and deletes them after a short time. The <a href="{{ get_url(path='/privacy/', trailing_slash=true) }}">privacy note</a> has the details.</p></details>

<details><summary>What happens to my e-mail address if I sign up?</summary><p id="email">First it gets one mail with a button to confirm it. Nothing goes on the list until you press that button, and an address nobody confirms is deleted after 7 days. After that, it is used for one thing: one mail when the campaign you signed up for opens. It is not shared, sold or added to anything else. Every mail has a link that deletes the address at once, or write to {{ <vh.mail to="donguru" subject="Remove me" /> }}. More in the <a href="{{ get_url(path='/privacy/', trailing_slash=true) }}">privacy note</a>.</p></details>

<details><summary>Why does the front page start like an oscilloscope?</summary><p id="intro">Because that is where I spend my days. It plays once when you arrive from outside, never while you move around the site, and a click, a key or a scroll skips it. "Replay intro" at the bottom plays it again. With reduced motion turned on in your system, it doesn't play at all.</p></details>

<details><summary>Why is the site dark?</summary><p id="dark">Most engineers look at code and scopes on dark screens. The toggle in the header switches to light, and the site remembers it.</p></details>
