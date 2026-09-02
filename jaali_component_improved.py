import math
import Rhino
import Rhino.Geometry as rg
from System.Collections.Generic import List

RoofPolysurface = List[rg.Brep]()
PerforatedPanels = List[rg.Brep]()
SolidPanels = List[rg.Brep]()
JaaliCurves = List[rg.Curve]()
VoidGeometry = List[rg.Brep]()  # Output aperture faces as geometry

if CanopySurface is not None:
    # Validate and set parameters
    u_n = max(2, int(U_Div)) if U_Div else 40
    v_n = max(2, int(V_Div)) if V_Div else 40
    panel_thk = float(Thickness) if Thickness is not None else 15.0  # Panel extrusion depth
    jaali_scale = float(JaaliScale) if JaaliScale is not None else 1.0  # Scale jaali pattern
    frame_width = float(FrameThickness) if FrameThickness is not None else 2.0  # Frame line thickness
    cull_th = float(CullThreshold) if CullThreshold is not None else 0.0  # Density control (0=all cells)

    tol = 0.01  # Tighter tolerance for better results
    min_thickness = 0.1
    panel_thk = max(panel_thk, min_thickness)

    # Normalize surface domain
    srf = CanopySurface.Duplicate()
    srf.SetDomain(0, rg.Interval(0.0, 1.0))
    srf.SetDomain(1, rg.Interval(0.0, 1.0))

    # Parse jaali pattern curves (traced from image via Potrace)
    jaali_curves = []
    if JaaliPatternCurves is not None:
        try:
            if hasattr(JaaliPatternCurves, '__iter__'):
                jaali_curves = list(JaaliPatternCurves)
            else:
                jaali_curves = [JaaliPatternCurves]
        except:
            jaali_curves = []
    
    # Parse brightness for density control (optional - controls which cells show pattern)
    brightness_grid = []
    try:
        if BrightnessList is not None:
            if hasattr(BrightnessList, '__iter__'):
                brightness_grid = list(BrightnessList)
            elif isinstance(BrightnessList, (int, float)):
                brightness_grid = [float(BrightnessList)]
    except Exception:
        pass  # If BrightnessList fails to parse, just leave it empty

    all_breps = List[rg.Brep]()
    
    # Generate the complete canopy grid
    for i in range(u_n):
        u0 = float(i) / float(u_n)
        u1 = float(i + 1) / float(u_n)
        
        for j in range(v_n):
            v0 = float(j) / float(v_n)
            v1 = float(j + 1) / float(v_n)
            
            # Calculate cell center for plane frame
            uc = (u0 + u1) * 0.5
            vc = (v0 + v1) * 0.5
            
            # Get the four corner points
            p00 = srf.PointAt(u0, v0)
            p10 = srf.PointAt(u1, v0)
            p11 = srf.PointAt(u1, v1)
            p01 = srf.PointAt(u0, v1)
            
            # Create outer boundary curve
            outer_pts = [p00, p10, p11, p01]
            outer_poly = rg.Polyline(outer_pts + [p00])
            outer_crv = outer_poly.ToNurbsCurve()
            
            # Get surface frame at cell center
            success, plane = srf.FrameAt(uc, vc)
            if not success:
                # Fallback: create plane from center point and Z axis
                center_pt = srf.PointAt(uc, vc)
                plane = rg.Plane(center_pt, rg.Vector3d.ZAxis)
            
            # Get surface normal and ensure proper orientation
            normal = plane.ZAxis
            normal.Unitize()
            
            # Extrude in the direction of the normal (outward from surface)
            extrude_vec = normal * panel_thk
            
            # Get brightness for this cell (controls density: which cells show pattern)
            cell_index = i * v_n + j
            show_cell = True
            if len(brightness_grid) > 0:
                if cell_index < len(brightness_grid):
                    try:
                        b = float(brightness_grid[cell_index])
                        show_cell = (b >= cull_th)  # Only show pattern if brightness >= threshold
                    except:
                        show_cell = True
                else:
                    show_cell = len(brightness_grid) > 0  # If indexed beyond grid, hide
            
            try:
                if not show_cell or len(jaali_curves) == 0:
                    # Create solid panel (no jaali pattern)
                    cell_breps = rg.Brep.CreatePlanarBreps(outer_crv, tol)
                    
                    if cell_breps and len(cell_breps) > 0:
                        top_b = cell_breps[0]
                        bot_b = top_b.DuplicateBrep()
                        bot_b.Transform(rg.Transform.Translation(extrude_vec))
                        bot_b.Flip()
                        
                        tile_faces = List[rg.Brep]()
                        tile_faces.Add(top_b)
                        tile_faces.Add(bot_b)
                        
                        side_srf = rg.Surface.CreateExtrusion(outer_crv, extrude_vec)
                        if side_srf:
                            side_brep = side_srf.ToBrep()
                            if side_brep:
                                tile_faces.Add(side_brep)
                        
                        joined = rg.Brep.JoinBreps(tile_faces, tol * 2.0)
                        if joined and len(joined) > 0:
                            solid_brep = joined[0]
                            if solid_brep.IsSolid:
                                SolidPanels.Add(solid_brep)
                                all_breps.Add(solid_brep)
                else:
                    # Create perforated panel with jaali pattern (Option 3: frame offset approach)
                    cell_center = srf.PointAt(uc, vc)
                    frame_curves = []
                    offset_dist = frame_width / 2.0
                    
                    for jc in jaali_curves:
                        try:
                            # Duplicate curve for transformation
                            scaled_crv = jc.DuplicateCurve()
                            
                            # Scale curve to cell size
                            curve_bbox = scaled_crv.GetBoundingBox(False)
                            curve_center = curve_bbox.Center
                            scale_xform = rg.Transform.Scale(curve_center, jaali_scale)
                            scaled_crv.Transform(scale_xform)
                            
                            # Transform to cell location
                            crv_bbox = scaled_crv.GetBoundingBox(False)
                            crv_center = crv_bbox.Center
                            move_vec = cell_center - crv_center
                            move_xform = rg.Transform.Translation(move_vec)
                            scaled_crv.Transform(move_xform)
                            
                            # Offset curve for frame thickness (Option 3)
                            # Create offset curves to represent frame width
                            offset_crv_out = scaled_crv.Offset(plane, offset_dist, tol, rg.CurveOffsetCornerStyle.Sharp)
                            offset_crv_in = scaled_crv.Offset(plane, -offset_dist, tol, rg.CurveOffsetCornerStyle.Sharp)
                            
                            if offset_crv_out and len(offset_crv_out) > 0:
                                frame_curves.append(offset_crv_out[0])
                            if offset_crv_in and len(offset_crv_in) > 0:
                                frame_curves.append(offset_crv_in[0])
                            
                            # Also track original curve for output
                            JaaliCurves.Add(scaled_crv)
                        except:
                            # Fallback: use original curve without offset
                            try:
                                scaled_crv = jc.DuplicateCurve()
                                curve_bbox = scaled_crv.GetBoundingBox(False)
                                curve_center = curve_bbox.Center
                                scale_xform = rg.Transform.Scale(curve_center, jaali_scale)
                                scaled_crv.Transform(scale_xform)
                                crv_bbox = scaled_crv.GetBoundingBox(False)
                                crv_center = crv_bbox.Center
                                move_vec = cell_center - crv_center
                                move_xform = rg.Transform.Translation(move_vec)
                                scaled_crv.Transform(move_xform)
                                frame_curves.append(scaled_crv)
                                JaaliCurves.Add(scaled_crv)
                            except:
                                pass
                    
                    # Create perforated geometry with frame curves
                    if len(frame_curves) > 0:
                        curves_list = List[rg.Curve]()
                        curves_list.Add(outer_crv)
                        
                        for fc in frame_curves:
                            curves_list.Add(fc)
                        
                        perf_breps = rg.Brep.CreatePlanarBreps(curves_list, tol)
                        
                        if perf_breps and len(perf_breps) > 0:
                            top_perf = perf_breps[0]
                            
                            # Create void geometry output
                            for fc in frame_curves:
                                try:
                                    void_brep = rg.Brep.CreatePlanarBreps(fc, tol)
                                    if void_brep and len(void_brep) > 0:
                                        VoidGeometry.Add(void_brep[0])
                                except:
                                    pass
                            
                            # Create bottom face
                            bot_perf = top_perf.DuplicateBrep()
                            bot_perf.Transform(rg.Transform.Translation(extrude_vec))
                            bot_perf.Flip()
                            
                            tile_faces = List[rg.Brep]()
                            tile_faces.Add(top_perf)
                            tile_faces.Add(bot_perf)
                            
                            # Extrude outer boundary
                            ext_outer = rg.Surface.CreateExtrusion(outer_crv, extrude_vec)
                            if ext_outer:
                                outer_brep = ext_outer.ToBrep()
                                if outer_brep:
                                    tile_faces.Add(outer_brep)
                            
                            # Extrude frame curves
                            for fc in frame_curves:
                                ext_inner = rg.Surface.CreateExtrusion(fc, extrude_vec)
                                if ext_inner:
                                    inner_brep = ext_inner.ToBrep()
                                    if inner_brep:
                                        tile_faces.Add(inner_brep)
                            
                            # Join all faces
                            joined = rg.Brep.JoinBreps(tile_faces, tol * 2.0)
                            if joined and len(joined) > 0:
                                perf_brep = joined[0]
                                if perf_brep.IsSolid:
                                    PerforatedPanels.Add(perf_brep)
                                    all_breps.Add(perf_brep)
                        
            except Exception as e:
                pass
    
    # Combine all breps into output
    if all_breps.Count > 0:
        for br in all_breps:
            RoofPolysurface.Add(br)
