foo:result = (x == 1, y == 2) : { result = 10 };
foo:result = (x == 2, y == 2) : { result = 20 };
foo:result = (x, y)           : { result = 99 }; // Fallback

[65000] = foo(1, 2); // Will be 10
[65000] = foo(2, 2); // Will be 20
[65000] = foo(5, 5); // Will be 99