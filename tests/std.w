int = (bytes[:4]): {
  value = bytes;
  value.add = (self[int], other[int]) : { 
      @asm(add, result, self, other); 
  } : result;
} : value;