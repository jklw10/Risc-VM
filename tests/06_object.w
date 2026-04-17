// 1. Register the Type (at comptime)
int = (bytes[:4]): {
  value = bytes;
  value.add = (self[int], other[int]) : { 
      @asm(add, result, self, other); 
  } : result;
} : value;

// 2. Object Spawn
my_num = int([:4]);

// 3. Method Call!
my_num.add(5);