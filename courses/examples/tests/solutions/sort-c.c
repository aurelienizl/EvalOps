#include <stdio.h>
#include <stdlib.h>

static int compare(const void *left, const void *right)
{
    int a = *(const int *)left, b = *(const int *)right;
    return (a > b) - (a < b);
}

int main(void)
{
    int count, values[1000];
    if (scanf("%d", &count) != 1)
        return 1;
    for (int i = 0; i < count; ++i)
        if (scanf("%d", &values[i]) != 1)
            return 1;
    qsort(values, count, sizeof *values, compare);
    for (int i = 0; i < count; ++i)
        printf("%s%d", i ? " " : "", values[i]);
    putchar('\n');
    return 0;
}
