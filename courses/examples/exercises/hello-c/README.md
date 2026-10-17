# First C Program

## File Tree

```text
hello-c/
└── main.c (to submit)
```

## Goal

Print exactly `Hello C` followed by a newline. Do not read input or print
anything else.

## Example

This program takes no input.

Output:

```text
Hello C
```

## Instructions

1. Connect to your development environment over SSH.
2. Create `main.c` in `/home/student/hello-c`.
3. Compile your program:
   ```sh
   cd ~/hello-c
   gcc -std=c11 -Wall -Wextra main.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
