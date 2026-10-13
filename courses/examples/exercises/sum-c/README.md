# Sum Two Integers in C

## Objective

Read two integers from standard input and print their sum followed by a newline.

## Working Directory

Create `sum.c` in `/home/student/sum-c`.

## Instructions

1. Read two integers with `scanf`.
2. Print their sum with `printf`. Do not print a prompt or other text.
3. Compile and test your program:
   ```bash
   cd ~/sum-c
   gcc -Wall -Wextra sum.c -o sum
   printf '2 3\n' | ./sum
   ```
   The output should be:
   ```text
   5
   ```
4. Check that negative integers and zero work too.
5. Click **Evaluate** on the platform.

You have three submissions. The evaluator checks that the source exists, compiles,
and produces the correct output for positive, negative, and zero inputs.
