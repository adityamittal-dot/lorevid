"""Run once on your laptop:  python auth.py
A browser opens -> choose your channel -> the token is printed for the GitHub secret YT_TOKEN."""
from upload import TOKEN, get_credentials

get_credentials(interactive=True)
print("\nCopy EVERYTHING below into the GitHub secret YT_TOKEN:\n")
print(open(TOKEN).read())
