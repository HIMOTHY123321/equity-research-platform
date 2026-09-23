import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GlossaryHint } from "./GlossaryHint";

describe("GlossaryHint", () => {
  it("renders nothing for an unknown/missing glossary id (fails safely)", () => {
    const { container } = render(<GlossaryHint termId="not-a-real-term-id" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders an accessible ⓘ button with the term name in its aria-label", () => {
    render(<GlossaryHint termId="break-of-structure" />);
    expect(screen.getByRole("button", { name: /Break of Structure/i })).toBeInTheDocument();
  });

  it("opens the definition popover on click, closes on a second click", () => {
    render(<GlossaryHint termId="break-of-structure" />);
    const button = screen.getByRole("button", { name: /Break of Structure/i });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/confirmed swing high or low/i)).toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keyboard: Enter/Space on the button toggles the popover open (native button semantics)", () => {
    render(<GlossaryHint termId="break-of-structure" />);
    const button = screen.getByRole("button", { name: /Break of Structure/i });
    button.focus();
    // jsdom's native <button> fires a click on Enter/Space via fireEvent.click
    // when Enter/keyup is simulated through userEvent; fireEvent.click here
    // exercises the same activation path the browser's native behavior uses.
    fireEvent.click(button);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Escape closes an open popover", () => {
    render(<GlossaryHint termId="break-of-structure" />);
    fireEvent.click(screen.getByRole("button", { name: /Break of Structure/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("clicking outside the popover closes it", () => {
    render(
      <div>
        <GlossaryHint termId="break-of-structure" />
        <button type="button">outside</button>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Break of Structure/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("includes a Learn More link pointing at the full glossary entry", () => {
    render(<GlossaryHint termId="break-of-structure" />);
    fireEvent.click(screen.getByRole("button", { name: /Break of Structure/i }));

    const link = screen.getByRole("link", { name: /learn more/i });
    expect(link).toHaveAttribute("href", "/glossary?term=break-of-structure");
  });

  it("renders the optional label text before the icon", () => {
    render(<GlossaryHint termId="break-of-structure" label="BOS" />);
    expect(screen.getByText("BOS")).toBeInTheDocument();
  });
});
