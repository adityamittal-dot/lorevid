"""Run once on your laptop:
    python auth.py            -> main project   (yt_client_secret.json  -> yt_token.json)
    python auth.py reserve    -> reserve project (yt_reserve_client_secret.json -> yt_reserve_token.json)
A browser opens -> choose your channel -> the token is printed for the GitHub secret."""
import sys
import upload

if len(sys.argv) > 1 and sys.argv[1] == "reserve":
    upload.SECRET, upload.TOKEN = "yt_reserve_client_secret.json", "yt_reserve_token.json"
    name = "YT_RESERVE_TOKEN"
else:
    name = "YT_TOKEN"
upload.get_credentials(interactive=True)
print(f"\nCopy EVERYTHING below into the GitHub secret {name}:\n")
print(open(upload.TOKEN).read())
