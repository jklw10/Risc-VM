// 1. Load the raw text buffer pointer into memory via macro
text_ptr = @embed(tests/input.txt);
text_len = 18; // Length of "hello world from W"

word_start = 0;
in_word = 0;

// 2. Iterate over the buffer (Temporal Pipeline)
(i = 0 : text_len) : {
    
    // Dereference pointer using manual arithmetic
    // Note: Reads a 32-bit word natively!
    char = [text_ptr + i];
    
    // Mask out the lowest 8 bits using an inline RISC-V instruction
    // to get our single ascii character!
    @asm(andi, char, char, 255);
    
    // Perform manual boolean logic (returns 0 or 1)
    is_space = char == 32;
    is_newline = char == 10;
    
    // Safe addition since a char cannot be both space AND newline
    is_delim = is_space + is_newline;
    
    // ---------------------------------------------------------
    // "if (is_delim)" -> Loops 1 time if true, 0 times if false
    (c1 = 0 : is_delim) : {
        
        // "if (in_word)"
        (c2 = 0 : in_word) : {
            
            // Boundary detected! Send start index to our simulated pixel/MMIO
            [65000] = word_start;
            
            // Reset state
            in_word = 0;
        }
    }
    
    // ---------------------------------------------------------
    // "if (!is_space && !is_newline)"
    is_not_space = char != 32;
    is_not_newline = char != 10;
    
    (c3 = 0 : is_not_space) : {
        (c4 = 0 : is_not_newline) : {
            
            not_in_word = in_word == 0;
            
            // "if (!in_word)"
            (c5 = 0 : not_in_word) : {
                word_start = i;
                in_word = 1;
            }
        }
    }
}

// 3. Flush the final word to MMIO if the text didn't end with a space
(c6 = 0 : in_word) : {
    [65000] = word_start;
}