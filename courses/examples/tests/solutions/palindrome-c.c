#include <stdio.h>
#include <string.h>

int main(void)
{
    char line[1002];
    if (!fgets(line, sizeof line, stdin))
        return 1;
    size_t length = strcspn(line, "\n");
    for (size_t i = 0; i < length / 2; ++i) {
        if (line[i] != line[length - 1 - i]) {
            puts("NO");
            return 0;
        }
    }
    puts("YES");
    return 0;
}
