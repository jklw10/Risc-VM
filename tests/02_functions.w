td = @import(tests/01_typedef.w);
int = td.int;

math = {
    .sum_n : result[int] = (n[int]) : {
        result = (i = 0 : n) : {
            result = result + i;
        };
        result = result + n;
    };
}