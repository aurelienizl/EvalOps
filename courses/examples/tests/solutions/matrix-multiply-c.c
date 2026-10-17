#include <stdio.h>

int main(void)
{
    int rows, inner, cols, a[10][10], b[10][10];
    if (scanf("%d %d %d", &rows, &inner, &cols) != 3)
        return 1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < inner; ++j)
            if (scanf("%d", &a[i][j]) != 1)
                return 1;
    for (int i = 0; i < inner; ++i)
        for (int j = 0; j < cols; ++j)
            if (scanf("%d", &b[i][j]) != 1)
                return 1;
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            int total = 0;
            for (int k = 0; k < inner; ++k)
                total += a[i][k] * b[k][j];
            printf("%s%d", j ? " " : "", total);
        }
        putchar('\n');
    }
    return 0;
}
