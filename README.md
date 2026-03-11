# FB Ad Media Uploader Interface

Local web app to upload assets into a Facebook ad account media library.

## Features

1. Upload videos directly from a public Google Drive folder link
2. Manual multi-image upload to ad account
3. Separate manual video upload

## Run

```bash
python3 -m pip install --user -r requirements.txt
python3 app.py
```

Open: `http://localhost:5050`

## Inputs required in UI

- Ad Account ID: e.g. `508817521835118` or `act_508817521835118`
- Access Token: token with `ads_management` permission
- Google Drive folder link (for Drive flow)

## Notes

- Drive flow uses resumable upload for videos (`/advideos`) to avoid large-file `413` errors.
- Image flow uses `/adimages` and supports selecting multiple images in one submission.
