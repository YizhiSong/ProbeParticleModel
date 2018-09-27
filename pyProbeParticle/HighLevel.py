#!/usr/bin/python

import os
import sys
import numpy     as np
import GridUtils as GU
import fieldFFT  as fFFT
import common    as PPU
import basUtils  as BU

import core
import cpp_utils

# ===== constants 
Fmax_DEFAULT = 10.0
Vmax_DEFAULT = 10.0

# ==== PP Relaxation

def Gauss(Evib, E0, w):
    return np.exp( -0.5*((Evib - E0)/w)**2);

def symGauss( Evib, E0, w):
    return Gauss(Evib, E0, w) - Gauss(Evib, -E0, w);

def meshgrid3d(xs,ys,zs):
    Xs,Ys,Zs = np.zeros()
    Xs,Ys = np.meshgrid(xs,ys)

def relaxedScan3D( xTips, yTips, zTips ):
    print ">>BEGIN: relaxedScan3D()"
    print " zTips : ",zTips
    ntips = len(zTips); 
    rTips = np.zeros((ntips,3))
    rs    = np.zeros((ntips,3))
    fs    = np.zeros((ntips,3))
    rTips[:,0] = 1.0
    rTips[:,1] = 1.0
    rTips[:,2] = zTips[::-1]  
    nx = len(zTips); ny = len(yTips ); nz = len(xTips);
    fzs    = np.zeros( ( nx,ny,nz ) );
    PPpos  = np.zeros( ( nx,ny,nz,3 ) );
    for ix,x in enumerate( xTips  ):
        sys.stdout.write('\033[K')
        sys.stdout.flush()
        sys.stdout.write("\rrelax ix: {}".format(ix))
        sys.stdout.flush()
        rTips[:,0] = x
        for iy,y in enumerate( yTips  ):
            rTips[:,1] = y
            itrav = core.relaxTipStroke( rTips, rs, fs ) / float( len(zTips) )
            fzs[:,iy,ix] = (fs[:,2].copy()) [::-1]
            PPpos[:,iy,ix,0] = rs[::-1,0] # - rTips[:,0]
            PPpos[:,iy,ix,1] = rs[::-1,1] # - rTips[:,1]
            PPpos[:,iy,ix,2] = rs[::-1,2] # - rTips[:,2]
    print "<<<END: relaxedScan3D()"
    return fzs,PPpos

def perform_relaxation (lvec,FFLJ,FFel=None, FFpauli=None, FFboltz=None,tipspline=None,bPPdisp=False,bFFtotDebug=False):
    print ">>>BEGIN: perform_relaxation()"
    if tipspline is not None :
        try:
            print " loading tip spline from "+tipspline
            S    = np.genfromtxt(tipspline )
            xs   = S[:,0].copy();  print "xs: ",   xs
            ydys = S[:,1:].copy(); print "ydys: ", ydys
            core.setTipSpline( xs, ydys )
            #Ks   = [0.0]
        except:
            print "cannot load tip spline from "+tipspline
            sys.exit()
    xTips,yTips,zTips,lvecScan = PPU.prepareScanGrids( )
    FF = FFLJ.copy()
    if ( FFel is not None):
        FF += FFel * PPU.params['charge']
        print "adding charge:", PPU.params['charge']
    if ( FFpauli is not None ):
        FF += FFpauli * PPU.params['Apauli']
    if FFboltz != None :
        FF += FFboltz
    if bFFtotDebug:
        GU.save_vec_field( 'FFtotDebug', FF, lvec )
    core.setFF_shape( np.shape(FF), lvec )
    core.setFF_Fpointer( FF )
    print "stiffness:", PPU.params['klat']
    core.setTip( kSpring = np.array((PPU.params['klat'],PPU.params['klat'],0.0))/-PPU.eVA_Nm )
    fzs,PPpos = relaxedScan3D( xTips, yTips, zTips )
    if bPPdisp:
        PPdisp=PPpos.copy()
        init_pos=np.array(np.meshgrid(xTips,yTips,zTips)).transpose(3,1,2,0)+np.array([PPU.params['r0Probe'][0],PPU.params['r0Probe'][1],-PPU.params['r0Probe'][2]])
        PPdisp-=init_pos
    else:
        PPdisp = None
    print "<<<END: perform_relaxation()"
    return fzs,PPpos,PPdisp,lvecScan

# ==== Forcefield grid generation

def prepareArrays( FF, Vpot ):
    if ( FF is None ):
        gridN = PPU.params['gridN']
        FF    = np.zeros( (gridN[2],gridN[1],gridN[0],3)    )
    else:
        PPU.params['gridN'] = np.shape( FF )
    core.setFF_Fpointer( FF )
    if ( Vpot ):
        V = np.zeros( (gridN[2],gridN[1],gridN[0])    )
        core.setFF_Epointer( V )
    else:
        V=None
    #core.setFF( gridF=FF, gridE=V )
    return FF, V 

def computeLJ( geomFile, speciesFile, save_format=None, computeVpot=False, Fmax=Fmax_DEFAULT, Vmax=Vmax_DEFAULT, ffModel="LJ" ):
    print ">>>BEGIN: computeLJ()"
    # --- load species (LJ potential)
    FFparams            = PPU.loadSpecies( speciesFile ) 
    elem_dict           = PPU.getFFdict(FFparams); # print elem_dict
    # --- load atomic geometry
    atoms,nDim,lvec     = BU.loadGeometry( geomFile, params=PPU.params )
    #print "DEBUG atoms : ", atoms
    atomstring          = BU.primcoords2Xsf( PPU.atoms2iZs( atoms[0],elem_dict ), [atoms[1],atoms[2],atoms[3]], lvec );
    PPU      .params['gridN'] = nDim; PPU.params['gridA'] = lvec[1]; PPU.params['gridB'] = lvec[2]; PPU.params['gridC'] = lvec[3] # must be before parseAtoms
    print PPU.params['gridN'],        PPU.params['gridA'],           PPU.params['gridB'],           PPU.params['gridC']
    iZs,Rs,Qs           = PPU.parseAtoms(atoms, elem_dict, autogeom=False, PBC = PPU.params['PBC'] )
    # --- prepare LJ parameters
    #print elem_dict
    iPP                 = PPU.atom2iZ( PPU.params['probeType'], elem_dict )
    # --- prepare arrays and compute
    FF,V                = prepareArrays( None, computeVpot )
    print "FFLJ.shape",FF.shape 
    #core.setGridN   ( nDim )
    #core.setGridCell( cell=lvec )
    core.setFF_shape( np.shape(FF), lvec )
    if ffModel=="Morse":
        REs = PPU.getAtomsRE( iPP, iZs, FFparams ); # print "cLJs",cLJs; np.savetxt("cLJs_3D.dat", cLJs);  exit()
        core.getMorseFF( Rs, REs )       # THE MAIN STUFF HERE
    elif ffModel=="vdW":
        cLJs = PPU.getAtomsLJ( iPP, iZs, FFparams ); # print "cLJs",cLJs; np.savetxt("cLJs_3D.dat", cLJs);  exit()
        core.getVdWFF( Rs, cLJs )       # THE MAIN STUFF HERE
    else:
        cLJs = PPU.getAtomsLJ( iPP, iZs, FFparams ); # print "cLJs",cLJs; np.savetxt("cLJs_3D.dat", cLJs);  exit()
        core.getLenardJonesFF( Rs, cLJs ) # THE MAIN STUFF HERE
    # --- post porces FFs
    if Fmax is not  None:
        print "Clamp force >", Fmax
        GU.limit_vec_field( FF, Fmax=Fmax )
    if (Vmax is not None) and computeVpot:
        print "Clamp potential >", Vmax
        V[ V > Vmax ] =  Vmax # remove too large values
    # --- save to files ?
    if save_format is not None:
        print "computeLJ Save ", save_format 
        GU.save_vec_field( 'FFLJ', FF, lvec,  data_format=save_format, head=atomstring )
        if computeVpot:
            GU.save_scal_field( 'VLJ', V, lvec,  data_format=save_format, head=atomstring )
    print "<<<END: computeLJ()"
    return FF, V, nDim, lvec

def computeELFF_pointCharge( geomFile, tip='s', save_format=None, computeVpot=False, Fmax=Fmax_DEFAULT, Vmax=Vmax_DEFAULT ):
    print ">>>BEGIN: computeELFF_pointCharge()"
    tipKinds = {'s':0,'pz':1,'dz2':2}
    tipKind  = tipKinds[tip]
    print " ========= get electrostatic forcefiled from the point charges tip=%s %i " %(tip,tipKind)
    # --- load atomic geometry
    #atoms,nDim,lvec     = BU .loadGeometry(options.input, params=PPU.params)
    FFparams            = PPU.loadSpecies( ) 
    elem_dict           = PPU.getFFdict(FFparams); # print elem_dict

    atoms,nDim,lvec     = BU .loadGeometry( geomFile, params=PPU.params )
    atomstring          = BU.primcoords2Xsf( PPU.atoms2iZs( atoms[0],elem_dict ), [atoms[1],atoms[2],atoms[3]], lvec );
    #elem_dict=None;  print " for FFel we need only Qs => elem_dict=None (ignore next warrning)"
    iZs,Rs,Qs=PPU.parseAtoms(atoms, elem_dict=elem_dict, autogeom=False, PBC=PPU.params['PBC'] )
    # --- prepare arrays and compute
    PPU.params['gridN'] = nDim; PPU.params['gridA'] = lvec[1]; PPU.params['gridB'] = lvec[2]; PPU.params['gridC'] = lvec[3]
    print PPU.params['gridN'], PPU.params['gridA'], PPU.params['gridB'], PPU.params['gridC']
    FF,V = prepareArrays( None, computeVpot )
    core.setFF_shape( np.shape(FF), lvec )
    core.getCoulombFF( Rs, Qs*PPU.CoulombConst, kind=tipKind ) # THE MAIN STUFF HERE
    # --- post porces FFs
    if Fmax is not  None:
        print "Clamp force >", Fmax
        GU.limit_vec_field( FF, Fmax=Fmax )
    if (Vmax is not None) and computeVpot:
        print "Clamp potential >", Vmax
        V[ V > Vmax ] =  Vmax # remove too large values
    # --- save to files ?
    if save_format is not None:
        print "computeLJ Save ", save_format 
        GU.save_vec_field( 'FFel',FF,lvec,data_format=save_format, head=atomstring )
        if computeVpot:
            GU.save_scal_field( 'Vel',V,lvec,data_format=save_format, head=atomstring )
    print "<<<END: computeELFF_pointCharge()"
    return FF, V, nDim, lvec

def computeElFF(V,lvec,nDim,tip,Fmax=None,computeVpot=False,Vmax=None, tilt=0.0 ):
    print " ========= get electrostatic forcefiled from hartree "
    rho = None
    multipole = None
    if type(tip) is dict:
        multipole = tip
    else:
        if tip in {'s','px','py','pz','dx2','dy2','dz2','dxy','dxz','dyz'}:
            rho = None
            multipole={tip:1.0}
        elif tip.endswith(".xsf"):
            rho, lvec_tip, nDim_tip, tiphead = GU.loadXSF(tip)
            if any(nDim_tip != nDim):
                sys.exit("Error: Input file for tip charge density has been specified, but the dimensions are incompatible with the Hartree potential file!")
    print " computing convolution with tip by FFT "
    #Fel_x,Fel_y,Fel_z      = fFFT.potential2forces(V, lvec, nDim, rho=rho, sigma=PPU.params['sigma'], multipole = multipole)
    Fel_x,Fel_y,Fel_z, Vout = fFFT.potential2forces_mem( V, lvec, nDim, rho=rho, sigma=PPU.params['sigma'], multipole = multipole, tilt=tilt )
    FFel = GU.packVecGrid(Fel_x,Fel_y,Fel_z)
    del Fel_x,Fel_y,Fel_z
    return FFel



