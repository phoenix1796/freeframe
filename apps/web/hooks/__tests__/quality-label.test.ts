import { describe, it, expect } from 'vitest'
import { qualityLabel } from '../use-video-player'

// The transcoder scales each rendition to fit inside a target box (1920x1080,
// 1280x720, 640x360) preserving aspect ratio, never cropping — so a non-16:9
// source's real encoded height comes out under the nominal tier (a 1790x956
// source in the 1080p box actually encodes at 1026px tall). qualityLabel
// buckets that back up to the standard tier name for display.
describe('qualityLabel', () => {
  it('buckets an under-height 1080p-box encode (1790x956 source) to "1080p"', () => {
    expect(qualityLabel(1026, 5_000_000)).toBe('1080p')
  })

  it('buckets an under-height 720p-box encode to "720p"', () => {
    expect(qualityLabel(684, 2_500_000)).toBe('720p')
  })

  it('buckets an under-height 360p-box encode to "360p"', () => {
    expect(qualityLabel(342, 800_000)).toBe('360p')
  })

  it('leaves an exact 16:9 encode at its own tier', () => {
    expect(qualityLabel(1080, 5_000_000)).toBe('1080p')
  })

  it('falls back to bitrate when height is 0 (audio-only rendition)', () => {
    expect(qualityLabel(0, 128_000)).toBe('128kbps')
  })

  it('falls back to the literal height above the highest standard tier', () => {
    expect(qualityLabel(3000, 20_000_000)).toBe('3000p')
  })
})
