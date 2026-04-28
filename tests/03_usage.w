td = @import(tests/01_typedef.w);
fd = @import(tests/02_functions.w);
int = td.int;
math = fd.math;

mmio[int] = 65000;

// Test 1: Basic Math & Operator Overloading
x[int] = 10;
y[int] = 5;

// x * y should trigger our loop-based multiplication operator (10 * 5 = 50)
mul_val[int] = x * y;

// Write 50 to MMIO to prove multiplication worked
[mmio] = mul_val;  


// Test 2: Function Calls
// Sum of 0+1+2+3+4+5 = 15
sum_val[int] = math.sum_n(5);

// Write 15 to MMIO to prove functions and loops worked
[mmio] = sum_val;


// Test 3: Arrays & Pointer Arithmetic
// Allocate 16 raw bytes on the stack
my_array = alloc[:16];

// Store our values into the array using index offsets
my_array[0] = 100;
my_array[4] = 200; // Offset by 4 bytes (size of our int)

// Read the value back from the array pointer
read_val[int] = my_array[4];

// Write 200 to MMIO to prove Array pointers and Dereferencing worked
[mmio] = read_val;


// Test 4: Nested Complex Expressions
// Should be (10 * 5) - (15) + 200 = 235
complex_calc[int] = mul_val - sum_val + read_val;

// Write 235 to MMIO 
[mmio] = complex_calc;