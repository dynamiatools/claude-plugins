// The surface module of a pointer target: a chip that says when the pointer is on it, so the hooks
// module shows that image's card, and when it is clicked, so the hooks module opens the image.
import type { ClientModule } from 'claude-code'

type Props = { label: string }

const Chip: ClientModule<Props, { isOver: boolean; isPressed?: boolean }> = (props, surface) => {
  surface.onPointer(event => {
    // A click is the left button let go over the chip it went down on.
    if (event.type === 'down') {
      if (event.button === 'left') surface.setState({ isOver: true, isPressed: true })
      return
    }
    if (event.type === 'up') {
      // A region not laid out yet (0 by 0) says nothing of where the pointer is.
      const isInside = surface.columns === 0 || (event.x >= 0 && event.y >= 0 && event.x < surface.columns && event.y < surface.rows)
      if (surface.state?.isPressed && isInside) surface.post({ isOver: true, isClicked: true })
      surface.setState({ isOver: isInside })
      return
    }
    // A move over the chip says so again: a card closed while the pointer stayed comes back.
    const isOver = event.type !== 'leave'
    surface.post({ isOver })
    if (isOver !== (surface.state?.isOver ?? false)) surface.setState({ isOver, isPressed: surface.state?.isPressed })
  })
  const { Text } = surface.elements
  return <Text color="claude" inverse={surface.state?.isOver === true}>{props.label}</Text>
}

export default Chip
