# Palindrome Check in C

## File Tree

```text
palindrome-c/
└── palindrome.c (to submit)
```

## Goal

Read one line containing zero to 1000 ASCII letters or digits. The final
input newline is optional and is not part of the string. Print `YES` if the
string reads the same forwards and backwards, or `NO` otherwise, followed
by a newline. Comparisons are case sensitive; the empty string is a palindrome.
All input satisfies these constraints.

## Example

Input:

```text
racecar
```

Output:

```text
YES
```

## Instructions

1. Connect to your development environment over SSH.
2. Create the exercise directory with `mkdir -p ~/palindrome-c`, then create
   `palindrome.c` inside it.
3. Compile your program:
   ```sh
   cd ~/palindrome-c
   gcc -std=c11 -Wall -Wextra palindrome.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
