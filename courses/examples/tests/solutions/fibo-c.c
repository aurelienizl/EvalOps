#include <stdio.h>

int main(void)
{
    int a = 0, b = 1;
    for (int i = 0; i < 10; ++i) {
        printf("%s%d", i ? " " : "", a);
        int next = a + b;
        a = b;
        b = next;
    }
    putchar('\n');
    return 0;
}
