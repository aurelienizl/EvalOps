# Matrix Multiplication in C

## File Tree

```text
matrix-multiply-c/
└── matrix.c (to submit)
```

## Goal

Read three integers `rows`, `inner`, and `cols`, each between 1 and 10.
Then read matrix A (`rows` rows and `inner` columns), followed by matrix B
(`inner` rows and `cols` columns), both in row-major order. Every element
is an integer between -100 and 100. Whitespace separates all input values.

Print the matrix product A times B, with `rows` lines and `cols` values per
line. Separate values with single spaces and end every row with a newline.
Do not print extra spaces or blank lines. All input satisfies these constraints.

## Example

Input:

```text
2 3 2
1 2 3
4 5 6
7 8
9 10
11 12
```

Output:

```text
58 64
139 154
```

## Instructions

1. Connect to your development environment over SSH.
2. Create `matrix.c` in `/home/student/matrix-multiply-c`.
3. Compile your program:
   ```sh
   cd ~/matrix-multiply-c
   gcc -std=c11 -Wall -Wextra matrix.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
