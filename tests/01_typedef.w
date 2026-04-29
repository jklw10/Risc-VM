
// Define the 'int' type as a 4-byte slice of memory
int : value = (bytes[:4]) : {
    value = bytes;

    // Define '+' using inline assembly
    .@op(+) : result[int] = (self[int], other[int]) : {
        @asm(add, result, self, other);
    };
    
    // Define '-' using inline assembly
    .@op(-) : result[int] = (self[int], other[int]) : {
        @asm(sub, result, self, other);
    };

    // Define '*' via a Temporal Pipeline (Loop)!
    // This perfectly tests your Dataflow loop syntax.
    // 'result' is implicitly allocated and zero-initialized.
    .@op(*) : result[int] = (self[int], other[int]) : {
        result = (i = 0 : other) : {
            result = result + self;
        };
    };
};
