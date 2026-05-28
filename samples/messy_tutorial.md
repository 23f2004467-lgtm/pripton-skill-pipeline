# Getting Comfortable with React Hooks

So, you've been writing React for a while with class components, or maybe you're
new to React entirely and everyone keeps telling you "just learn hooks." Either
way, this is a tutorial-ish walkthrough of how hooks actually work, with some
of the gotchas you only discover after you ship them to production.

We're going to bounce between concept and code. If you're skimming, the code
blocks are the important bits. If you're reading carefully, the prose is where
the actual reasoning lives.

## What is a Hook, even

A hook is just a function. That's it. The wild thing is that hooks behave
differently *based on where you call them*. React keeps track of which hook
you're on by counting calls, in order, on every render. This is why all the
documentation screams at you to never call hooks inside conditionals or loops.
If the order changes between renders, React loses track of which state
corresponds to which `useState` call, and everything explodes.

```js
function Counter() {
  const [count, setCount] = useState(0);
  return (
    <button onClick={() => setCount(count + 1)}>
      Clicked {count} times
    </button>
  );
}
```

That's the simplest possible hook usage. `useState` returns a tuple: the
current value, and a setter. When you call the setter, the component re-renders.

### The mental model

If you remember nothing else, remember this: **components are functions that
re-run on every render, and hooks are how those functions remember things
across re-runs.** That's the whole game.

State, effects, refs, context — they're all variations on "remember this
thing between renders" with slightly different semantics.

## useState in more depth

`useState` is the workhorse. A few things that bite people:

You can pass an initializer function for expensive initial values. If you
write `useState(expensiveComputation())`, that function runs every render,
even though only the *first* render's value is used. If you write
`useState(() => expensiveComputation())`, the function only runs once. This
matters more than you'd think for components that mount and unmount frequently.

The setter function can take either a value or a function. The function form
is what you want when the new state depends on the old state, because
React batches updates — and if you write `setCount(count + 1)` twice in a row,
both calls see the same stale `count`. Use `setCount(c => c + 1)` instead.

```js
// Wrong — both calls see count=0, end state is 1, not 2
setCount(count + 1);
setCount(count + 1);

// Right — functional update, end state is 2
setCount(c => c + 1);
setCount(c => c + 1);
```

This is the kind of thing that works fine in development with React strict
mode off and then surprises you in production. Use the functional form when
in doubt.

## useEffect — the one everyone gets wrong

`useEffect` is for side effects: subscriptions, data fetching, manual DOM
mutations, timers. Anything that touches the world outside the component.

The shape:

```js
useEffect(() => {
  // setup
  return () => {
    // cleanup (optional)
  };
}, [dependencies]);
```

The dependency array is the part everyone fights with. The rule is: every
value from the component scope that your effect reads must be in the array.
The React team ships an ESLint rule called `exhaustive-deps` that catches
when you violate this. Turn it on. It will save you many evenings.

People sometimes try to "fix" the dependency warning by removing the array
entirely. That makes the effect run on every render, which is almost never
what you want and usually causes infinite re-render loops if the effect
updates state.

A common pattern that confuses people is data fetching:

```js
useEffect(() => {
  let cancelled = false;
  fetchUser(userId).then(user => {
    if (!cancelled) setUser(user);
  });
  return () => { cancelled = true; };
}, [userId]);
```

The `cancelled` flag handles the race condition where the user navigates
away or `userId` changes before the fetch returns. Without it, you can set
state on an unmounted component or with stale data.

These days, most teams reach for a data-fetching library — React Query,
SWR, RTK Query — that handles all this. Hand-rolling fetching with useEffect
is fine for learning but you'll outgrow it.

## useRef and the escape hatch

`useRef` returns a mutable object with a `.current` property. Updating
`.current` does NOT trigger a re-render. This is useful for two unrelated
things that share an API:

First, holding a reference to a DOM node:

```js
const inputRef = useRef(null);
// later in JSX:
<input ref={inputRef} />
// even later:
inputRef.current.focus();
```

Second, holding mutable values across renders without triggering re-renders.
Timer IDs, previous values, anything you want to remember but not display.

If you find yourself reaching for `useRef` to "fix" a render loop, that's
usually a sign something is wrong with your dependency array or your state
shape, not that you actually want a ref.

## Custom hooks

Any function whose name starts with `use` and that calls other hooks is a
custom hook. This is how you extract reusable stateful logic.

```js
function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initialValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue];
}
```

Now any component can use `useLocalStorage` and get persistence for free.
The whole React ecosystem of third-party hooks — useDebounce, useMediaQuery,
useIntersectionObserver — is built on this pattern.

## What about useReducer, useMemo, useCallback

These get talked up a lot but you don't need them for most components.

`useReducer` is `useState`'s overengineered cousin. Reach for it when state
updates are complex enough that having all the logic in one place (the
reducer) helps. If your `useState` calls are turning into a tangle of
interdependent setters, `useReducer` might clean it up.

`useMemo` memoizes expensive computations. `useCallback` memoizes function
references. Both have non-trivial overhead themselves — wrapping every
function in `useCallback` "for performance" usually makes your app slower,
not faster. Profile first.

## The performance trap

People will tell you React is slow and you need to memoize everything. This
is almost always wrong for new code. Build the simple version first. Use the
React DevTools profiler to find actual slow renders. Then memoize where it
matters.

The exception is large lists. If you're rendering thousands of items, you
need windowing (react-window, react-virtual) regardless of memoization.

## Closing thoughts

Hooks took the React community a few years to fully internalize. The mental
model — components are functions that re-run, hooks remember things — is the
core. Everything else is application of that idea.

If something is weird, the answer is almost always one of three things:
your dependency array is wrong, your state is in the wrong place (lift it
up or push it down), or you're trying to imperatively control something
React thinks it's controlling. Start there.
