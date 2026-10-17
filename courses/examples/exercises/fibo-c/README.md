# Fibonacci Sequence in C

## File Tree

```text
fibo-c/
└── fibo.c (to submit)
```

## Goal

Print the first ten Fibonacci numbers, starting with `F(0) = 0` and
`F(1) = 1`. Each later number is the sum of the preceding two.
Separate the numbers with single spaces, with no leading or trailing space,
and finish with a newline. The program does not read input.

## Example

This program takes no input.

Output:

```text
0 1 1 2 3 5 8 13 21 34
```

## Instructions

1. Connect to your development environment over SSH.
2. Create `fibo.c` in `/home/student/fibo-c`.
3. Compile your program:
   ```sh
   cd ~/fibo-c
   gcc -std=c11 -Wall -Wextra fibo.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
