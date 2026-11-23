# Christian Approvals

Passcode-protected review dashboard for Ian Banner. The live page is a static site. It decrypts `data.enc.json` in the browser, then can write a decision into the private repo `ianbanner/christian-approvals-ticks`. It never publishes a post.

Real items, the real passcode, and the ticks token are never stored in this repo as plaintext. The only content committed here is encrypted. The file in git now is a fake sample. It opens with the placeholder passcode `example-only`.

Live site: https://ianbanner.github.io/christian-approvals/

Save that address to an iPhone home screen. The icon, title, and full-screen meta tags are already set.

## Unlock the page

Enter the passcode. Tick **Remember on this device** only on a phone you trust. That stores the passcode in local storage on that phone and nowhere else. Leave it unticked and the passcode stays in memory for the visit only.

Each card shows the platform, kind, author, original link, summary, whether it was read in full, the draft, flags, and deadline. Approve, Reject, or Change writes `decisions/<id>.json` in the private ticks repo. Change asks for change notes first. An optional note can go with any decision. If a write fails, the card shows the error. Loading the page reads decisions already in that repo and marks the cards.

## Replace the sample with real data

Create the private repo `ianbanner/christian-approvals-ticks` if it does not exist yet. Create a fine-grained personal access token whose only repository is that one, with Contents set to read and write. Put plaintext items in a local `items.json`. That filename is gitignored. Do not commit it.

`items.json` is a JSON array. Each object needs:

`id`, `section` (`long_form`, `short_form`, or `audiences`), `platform`, `kind`, `author`, `url`, `summary`, `read_in_full` (true or false), `draft`, `flags` (array of strings), `deadline_iso` (UTC `YYYY-MM-DDTHH:MM:SSZ`, or empty), `deadline_label`, `status`, `source_bot`.

Ids use letters, numbers, dots, underscores, and hyphens, because the id becomes the decision file name.

```bash
pip install -r requirements.txt
export CA_PASSCODE='a long passphrase you will type on the phone'
export CA_TICKS_TOKEN='the fine-grained token'
python3 tools/publish_data.py items.json
python3 tools/publish_data.py items.json --push
```

`publish_data.py` reads the passcode and token from the environment, builds `{ generated_at, ticks_repo, ticks_token, items }`, and encrypts it to `data.enc.json`. It does not print the passcode, the token, or the items. `--push` commits and pushes only `data.enc.json` to `main`.

Anyone who knows the passcode can read the token from the encrypted file. Use a strong passcode, and keep the token scoped to the ticks repo.

## Read decisions

```bash
export CA_TICKS_TOKEN='the fine-grained token'
python3 tools/read_ticks.py
python3 tools/read_ticks.py --archive
```

The first command prints every decision in `decisions/` as JSON. `--archive` moves those files to `archive/<UTC date>/` in the private repo.

## Tests

```bash
python3 -m unittest discover -s tests
```

The round trip encrypts with `tools/publish_data.py` and decrypts with `crypto.js`, the same WebCrypto steps the page uses. The decision test checks the `{ id, decision, note, decided_at }` file.

## Encryption

AES-GCM, 256-bit key, 12-byte IV, 16-byte salt. The key is PBKDF2-HMAC-SHA256 with 250,000 iterations. Salt and IV are random and stored in `data.enc.json`. The page refuses iteration counts under 250,000 or over 1,000,000. `crypto.js` and `tools/crypto_box.py` implement the same steps.
