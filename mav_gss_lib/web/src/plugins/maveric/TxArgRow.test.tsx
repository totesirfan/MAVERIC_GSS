import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import TxArgRow from './TxArgRow'

const noop = () => {}

// Vitest-native assertions (no jest-dom): getByText throws when not found,
// queryByText returns null. Use .toBeNull() / .not.toBeNull().

describe('TxArgRow', () => {
  it('renders the arg name', () => {
    render(
      <TxArgRow arg={{ name: 'year', type: 'year_2digit_t' }}
                value="" onChange={noop} onEnter={noop} disabled={false} />
    )
    expect(screen.getByText('year')).not.toBeNull()
  })

  it('renders description as a hint under the input when present', () => {
    render(
      <TxArgRow arg={{
        name: 'year', type: 'year_2digit_t',
        description: '2-digit year (e.g. 26 for 2026, NOT 2026)',
      }} value="" onChange={noop} onEnter={noop} disabled={false} />
    )
    expect(screen.getByText(/2-digit year/i)).not.toBeNull()
  })

  it('renders valid_range as a chip next to the arg name', () => {
    render(
      <TxArgRow arg={{
        name: 'year', type: 'year_2digit_t', valid_range: [0, 99],
      }} value="" onChange={noop} onEnter={noop} disabled={false} />
    )
    expect(screen.getByText('0–99')).not.toBeNull()
  })

  it('omits the chip when valid_range is absent', () => {
    render(
      <TxArgRow arg={{ name: 'cmd_args', type: 'EmbeddedCmdArgs' }}
                value="" onChange={noop} onEnter={noop} disabled={false} />
    )
    expect(screen.queryByText(/[0-9]+–[0-9]+/)).toBeNull()
  })

  it('calls onChange when the input changes', () => {
    const onChange = vi.fn()
    render(
      <TxArgRow arg={{ name: 'year', type: 'year_2digit_t' }}
                value="" onChange={onChange} onEnter={noop} disabled={false} />
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '26' } })
    expect(onChange).toHaveBeenCalledWith('26')
  })
})
