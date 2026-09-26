# Make Your Own OS

![MyOS: Firefox with the MyOS start page above its own bar](images/myos.png)

While building OnlyBrowserOS, I also wrote a hands-on course that teaches the
same method from an empty folder. It builds **MyOS**, a small system that logs
in by itself and opens Firefox full screen above a bar you write yourself. It
has its own repository:

**[github.com/AnIntellectualBeing/createyourdistro](https://github.com/AnIntellectualBeing/createyourdistro)**

- `COURSE.md`: concepts (the boot chain, the file system, packages,
  systemd, live systems, graphics, chroot), then 11 lessons, each with every
  command explained, and a customisation cookbook
- `EXERCISES.md`: things to try after each lesson
- `myos/`: the working example (`build.sh` runs each lesson as one step)
- Releases: `myos-0.1-amd64.iso`, the finished result

The course ends by mapping each MyOS file to its OnlyBrowserOS counterpart.
For the exact commands of the OnlyBrowserOS build itself, see
[`06-build-from-scratch.md`](06-build-from-scratch.md).
