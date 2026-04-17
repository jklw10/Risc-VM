std = @import(tests/std.w);

my_num = std.int(@embed(tests/number.txt));

my_num.add(5);