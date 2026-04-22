// ==========================================
// tokenizer.w
// The .w Self-Hosted Lexer
// ==========================================
int = (bytes[:4]): {
  value = bytes;
  value.@op(+) = (self[int], other[int]) : { 
      @asm(add, result, self, other); 
  } : result;
  value.@op(*) = (self[int], other[int]) : { 
      (i = :self):{
          result = result + other
      } : result;
  } : result;
} : value;

lexer = (bytes[:1]) : {
    value = bytes;
    // Lexer State Constants
    value.STATE_DEFAULT = 0;
    value.STATE_IDENT   = 1;
    value.STATE_NUM     = 2;
    value.STATE_SYMBOL  = 3;
} : value;

// A Token requires 3 integers: [Type, StartOffset, Length].
// Because DoD favors flat arrays, the caller allocates a massive 
// single array, and we use a stride of 3 to store struct properties.
tokenize = (self[lexer], source[int], src_len, tokens[int]) : {
    current_state = self.STATE_DEFAULT;
    tok_start = 0;
    tok_count = 0;
    // Process the source code as a continuous data stream
    (0 : src_len)[i] : {
        char = source[i];
        // 1. Character Classifications (Branchless Boolean Math)
        is_space = (char == 32) + (char == 10) + (char == 13) + (char == 9);
        is_space = is_space > 0; // Clamp to 1
        is_alpha = ((char > 64) * (char < 91)) + ((char > 96) * (char < 123)) + (char == 95);
        is_alpha = is_alpha > 0; 
        is_num = (char > 47) * (char < 58);
        is_symbol = (is_space == 0) * (is_alpha == 0) * (is_num == 0);
        // 2. Determine if we need to close and emit the current token
        // We break a token if we hit a space, OR if we hit a symbol, 
        // OR if the current state IS a symbol (symbols are 1 char in this pass)
        should_emit = is_space + is_symbol + (current_state == self.STATE_SYMBOL);
        should_emit = (should_emit > 0) * (current_state != self.STATE_DEFAULT);
        (0 : should_emit)[_] : {
            // Write to the token memory arena (Stride of 3)
            base = tok_count * 3;
            tokens[base + 0] = current_state;
            tokens[base + 1] = tok_start;
            tokens[base + 2] = i - tok_start;
            tok_count = tok_count + 1;
            current_state = self.STATE_DEFAULT;
        };
        // 3. State Transitions (Only apply if we are currently in DEFAULT)
        (0 : current_state == self.STATE_DEFAULT)[_] : {
            // If it's an alpha, begin IDENT
            (0 : is_alpha)[_] : {
                current_state = self.STATE_IDENT;
                tok_start = i;
            };
            // If it's a number, begin NUM
            (0 : is_num)[_] : {
                current_state = self.STATE_NUM;
                tok_start = i;
            };
            // If it's a symbol, begin SYMBOL
            (0 : is_symbol)[_] : {
                current_state = self.STATE_SYMBOL;
                tok_start = i;
            };
        };
    };
    // Emit final token if the file ends without a trailing space
    (0 : current_state != self.STATE_DEFAULT)[_] : {
        base = tok_count * 3;
        tokens[base + 0] = current_state;
        tokens[base + 1] = tok_start;
        tokens[base + 2] = src_len - tok_start;
        tok_count = tok_count + 1;
    };
} : tok_count; // Return the total number of tokens parsed


// ==========================================
// The Context Owner (Caller)
// ==========================================

// 1. Allocate 10kb of source memory and 30kb for max 10,000 tokens
source_buffer = alloc[:10000][int];
token_buffer  = alloc[:30000][int];

// 2. Fetch the file via Syscall/Hostcall (Fictionalized @asm macro implementation)
// This loads file text into memory and returns the character count
source_len = @asm(host_call, 1, source_buffer); 


l = lexer(0)
// 3. Execute the pipeline! 
// Data goes in, total token count comes out. State is observable.
total_tokens = l.tokenize(source_buffer, source_len, token_buffer);