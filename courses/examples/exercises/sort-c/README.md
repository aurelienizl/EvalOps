# Sort Integers in C

## File Tree

```text
sort-c/
└── sort.c (to submit)
```

## Goal

Read an integer `n` (`0 <= n <= 1000`), followed by `n` integers between
`-1000000000` and `1000000000`, inclusive. Input values are separated by
arbitrary whitespace. Print the values in ascending order, preserving
duplicates, separated by single spaces with no leading or trailing space.
End with a newline. When `n` is zero, print only a newline.
All input satisfies these constraints.

## Example

Input:

```text
5
3 -1 3 0 2
```

Output:

```text
-1 0 2 3 3
```

## Instructions

1. Connect to your development environment over SSH.
2. Create the exercise directory with `mkdir -p ~/sort-c`, then create
   `sort.c` inside it.
3. Compile your program:
   ```sh
   cd ~/sort-c
   gcc -std=c11 -Wall -Wextra sort.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
