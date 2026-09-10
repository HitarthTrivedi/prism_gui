PRISM — installing on a Mac from this zip
==========================================

You need: a Mac (Apple silicon or Intel), an internet connection for the
first run, and Google Chrome (https://www.google.com/chrome/) signed in to
the AI tools you use. Nothing else — no Python, no Homebrew, no admin
password.

1. Unzip. Put the "Prism" folder anywhere you like (Applications, Desktop,
   Documents). Do not move it afterwards — the installer builds inside it.

2. Double-click  "Install and Run Prism.command".

   If macOS says it "cannot be opened because it is from an unidentified
   developer": right-click the file → Open → Open. You only do this once.
   (That message is why a signed DMG is coming later.)

3. A Terminal window opens and does the setup: it finds a Python on the Mac
   or fetches its own, makes a private environment, installs Prism's
   requirements and the bundled Chromium, then starts Prism. The first run
   takes a few minutes and about 1.5 GB of disk. Every run after that
   starts Prism straight away.

   Keep the Terminal window open while Prism is running.

4. Sign in to your AI tools in Google Chrome once (ChatGPT, Claude, Canva,
   Perplexity …). Prism drives that Chrome.

If something goes wrong, the whole record is in  install.log  in the Prism
folder. Send that file.

To remove Prism: delete the folder. Your settings live in ~/.prism.
To reinstall from scratch: delete .venv and runtime inside the folder and
double-click the .command again.

Optional:
  · Voice input needs PortAudio (brew install portaudio); without it,
    typing works as normal.
  · The STEP add-on's CAD kernel (cadquery) is large; set
    PRISM_SKIP_CADQUERY=1 before running to skip it.
