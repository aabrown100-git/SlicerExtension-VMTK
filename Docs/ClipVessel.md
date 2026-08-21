# Clip Vessel
This module serves to clip or truncate a vessel based on user provider points. The user must provide a surface as input (in either model or segmentation format) as well as vessel centerlines created by the VMTK module [**ExtractCenterline**.](https://github.com/vmtk/SlicerExtension-VMTK/blob/master/Docs/ExtractCenterline.md). All branches/vessels should contain a centerline otherwise the clipping may produce undesired geometries in regions without a centerline.  Finally, the user must provide a list of fiducial points that represent where the model will be clipped. The first point is assumed to be the vessel inlet and will clip accordingly. If the output model needs to be capped this can be triggered by the checkbox. The module outputs the clipped surface.

![Clip points](ClipVessel_0.png)
**Placement of markup points to define clipping locations**

![Clipped vessel](ClipVessel_1.png)
**Clipped vessel**


## Advanced
Advanced options include preprocessing of the input surface and the addition of flow extensions.
Refer to [here](https://github.com/vmtk/SlicerExtension-VMTK/blob/master/Docs/ExtractCenterline.md#:~:text=Extract%20centerline-,Preprocessing,-The%20module%20requires) for preprocessing options related to the input surface. When creating flow extensions the user can control the extension length ratio, the extension mode, and the interpolation mode. The extension length ratio sets the length of each extension as a multiple of the radius of the vessel end that it is attached to (for example, 2 adds an extension that is twice as long as the radius of that clipped end, default 2). The extension mode selects the direction of the extension: along the direction of the centerline at the vessel end, or along the normal of the clipped boundary. The interpolation mode selects how the original outlet is transitioned to a circular outlet: linear switches to the circular cross-section immediately at the clipped boundary, while thin plate spline blends the two gradually. The transition length ratio is only used by the thin plate spline interpolation: it sets how much of the extension length is used for the transition (0 = circular immediately at the clipped boundary, 1 = the whole extension, default 0.25).

![Clipped vessel extended](ClipVessel_2.png)
**Clipped vessel with flow extensions**


## Acknowledgement
This module has been contributed by David Molony and is heavily based on the ExtractCenterline module.