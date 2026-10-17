# Comparing a string from both ends

Use `fgets` with a buffer large enough for 1000 characters, the input newline,
and the terminating null byte. Remove the input newline before comparing.

Compare the first and last characters, then move both positions inward.
Avoid subtracting one from an unsigned zero length.

Examples: `abba` -> YES, `Aa` -> NO, an empty line -> YES.
